import * as cdk from 'aws-cdk-lib/core';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as events from 'aws-cdk-lib/aws-events';
import * as eventsTargets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';

const DOMAIN_NAME = 'bytes.finaldivision.com';
const HOSTED_ZONE_NAME = 'finaldivision.com';

const LAMBDA_NAMES = ['release_radar', 'hn_digest', 'gh_trending'] as const;

export class TechBytesStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------
    // 1. SSM Parameter names (Lambdas read values at runtime)
    // ---------------------------------------------------------------
    const OPENAI_KEY_PARAM = '/tech-bytes/openai-api-key';
    const GITHUB_TOKEN_PARAM = '/tech-bytes/github-token';

    // ---------------------------------------------------------------
    // 2. S3 Bucket — site files at root, data at data/ prefix
    // ---------------------------------------------------------------
    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          prefix: 'data/',
          expiration: cdk.Duration.days(90),
        },
      ],
    });

    // ---------------------------------------------------------------
    // 3. Route53 Hosted Zone (existing)
    // ---------------------------------------------------------------
    const hostedZone = route53.HostedZone.fromLookup(this, 'HostedZone', {
      domainName: HOSTED_ZONE_NAME,
    });

    // ---------------------------------------------------------------
    // 4. ACM Certificate (us-east-1 for CloudFront)
    // ---------------------------------------------------------------
    // DnsValidatedCertificate is deprecated but is the simplest way
    // to create a cross-region cert validated via Route53.
    const certificate = new acm.DnsValidatedCertificate(this, 'SiteCert', {
      domainName: DOMAIN_NAME,
      hostedZone,
      region: 'us-east-1',
    });

    // ---------------------------------------------------------------
    // 5. CloudFront Distribution
    // ---------------------------------------------------------------
    const originAccessIdentity = new cloudfront.OriginAccessIdentity(
      this,
      'OAI',
      { comment: 'OAI for Tech Bytes site bucket' },
    );

    siteBucket.grantRead(originAccessIdentity);

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: new origins.S3Origin(siteBucket, {
          originAccessIdentity,
        }),
        viewerProtocolPolicy:
          cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      defaultRootObject: 'index.html',
      domainNames: [DOMAIN_NAME],
      certificate,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      errorResponses: [
        {
          httpStatus: 404,
          responsePagePath: '/404.html',
          responseHttpStatus: 404,
          ttl: cdk.Duration.minutes(5),
        },
      ],
    });

    // ---------------------------------------------------------------
    // 6. Route53 A record -> CloudFront
    // ---------------------------------------------------------------
    new route53.ARecord(this, 'SiteAliasRecord', {
      zone: hostedZone,
      recordName: DOMAIN_NAME,
      target: route53.RecordTarget.fromAlias(
        new targets.CloudFrontTarget(distribution),
      ),
    });

    // ---------------------------------------------------------------
    // 7. Lambda Functions (Python 3.12)
    // ---------------------------------------------------------------

    // Shared bundled asset — installs pip deps and copies source
    const lambdaCode = lambda.Code.fromAsset('../lambdas', {
      bundling: {
        image: lambda.Runtime.PYTHON_3_12.bundlingImage,
        command: [
          'bash',
          '-c',
          'pip install -r requirements.txt -t /asset-output && cp -r . /asset-output',
        ],
      },
    });

    const lambdaFunctions = LAMBDA_NAMES.map((name) => {
      const fn = new lambda.Function(this, `${pascalCase(name)}Function`, {
        runtime: lambda.Runtime.PYTHON_3_12,
        code: lambdaCode,
        handler: `${name}.handler.handler`,
        timeout: cdk.Duration.minutes(5),
        memorySize: 512,
        environment: {
          DATA_BUCKET_NAME: siteBucket.bucketName,
          OPENAI_KEY_SSM_PARAM: OPENAI_KEY_PARAM,
          GITHUB_TOKEN_SSM_PARAM: GITHUB_TOKEN_PARAM,
        },
      });

      // Grant write to the data/ prefix only
      siteBucket.grantPut(fn, 'data/*');

      // Grant read access to SSM parameters
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['ssm:GetParameter'],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter${OPENAI_KEY_PARAM}`,
            `arn:aws:ssm:${this.region}:${this.account}:parameter${GITHUB_TOKEN_PARAM}`,
          ],
        }),
      );

      return { name, fn };
    });

    // ---------------------------------------------------------------
    // 8. EventBridge Schedules
    // ---------------------------------------------------------------
    const schedules: Record<string, events.Schedule> = {
      release_radar: events.Schedule.expression('cron(0 6 * * ? *)'),
      hn_digest: events.Schedule.expression('cron(0 8 * * ? *)'),
      gh_trending: events.Schedule.expression('cron(0 7 ? * MON *)'),
    };

    for (const { name, fn } of lambdaFunctions) {
      new events.Rule(this, `${pascalCase(name)}Schedule`, {
        schedule: schedules[name],
        targets: [new eventsTargets.LambdaFunction(fn)],
        description: `Scheduled trigger for ${name}`,
      });
    }

    // ---------------------------------------------------------------
    // 9. Site Deployment (Astro build output)
    // ---------------------------------------------------------------
    new s3deploy.BucketDeployment(this, 'DeploySite', {
      sources: [s3deploy.Source.asset('../site/dist')],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ['/*'],
    });

    // ---------------------------------------------------------------
    // 10. GitHub Actions OIDC Role
    // ---------------------------------------------------------------
    const ghProvider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
      this,
      'GitHubOidc',
      `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`,
    );

    const deployRole = new iam.Role(this, 'GitHubActionsRole', {
      assumedBy: new iam.WebIdentityPrincipal(
        ghProvider.openIdConnectProviderArn,
        {
          StringEquals: {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          },
          StringLike: {
            'token.actions.githubusercontent.com:sub': 'repo:datj9/tech-bytes:*',
          },
        },
      ),
      description: 'Role assumed by GitHub Actions for Tech Bytes CI/CD',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AdministratorAccess'),
      ],
    });

    // ---------------------------------------------------------------
    // Outputs
    // ---------------------------------------------------------------
    new cdk.CfnOutput(this, 'SiteUrl', {
      value: `https://${DOMAIN_NAME}`,
    });

    new cdk.CfnOutput(this, 'DistributionDomainName', {
      value: distribution.distributionDomainName,
    });

    new cdk.CfnOutput(this, 'BucketName', {
      value: siteBucket.bucketName,
    });

    new cdk.CfnOutput(this, 'GitHubActionsRoleArn', {
      value: deployRole.roleArn,
      description: 'Set this as AWS_ROLE_ARN secret in GitHub repo',
    });
  }
}

/** Convert snake_case to PascalCase */
function pascalCase(s: string): string {
  return s
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}
