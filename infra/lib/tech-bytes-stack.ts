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
import * as ses from 'aws-cdk-lib/aws-ses';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import { Construct } from 'constructs';

const DOMAIN_NAME = 'bytes.finaldivision.com';
const HOSTED_ZONE_NAME = 'finaldivision.com';

const LAMBDA_NAMES = ['release_radar', 'hn_digest', 'gh_trending', 'email_digest'] as const;

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

    // CloudFront Function to rewrite /path → /path/index.html
    const urlRewrite = new cloudfront.Function(this, 'UrlRewrite', {
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else if (!uri.includes('.')) {
    request.uri += '/index.html';
  }
  return request;
}
      `),
      runtime: cloudfront.FunctionRuntime.JS_2_0,
    });

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: new origins.S3Origin(siteBucket, {
          originAccessIdentity,
        }),
        viewerProtocolPolicy:
          cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        functionAssociations: [
          {
            function: urlRewrite,
            eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
          },
        ],
      },
      defaultRootObject: 'index.html',
      domainNames: [DOMAIN_NAME],
      certificate,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
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
    // 6b. SES Domain Identity (verified via Route53 DNS)
    // ---------------------------------------------------------------
    const sesIdentity = new ses.EmailIdentity(this, 'SesDomainIdentity', {
      identity: ses.Identity.publicHostedZone(hostedZone),
      mailFromDomain: `mail.${DOMAIN_NAME}`,
    });

    // ---------------------------------------------------------------
    // 6c. SSM Parameter for email subscribers (comma-separated)
    // ---------------------------------------------------------------
    const SUBSCRIBERS_PARAM = '/tech-bytes/subscribers';
    new ssm.StringParameter(this, 'SubscribersParam', {
      parameterName: SUBSCRIBERS_PARAM,
      stringValue: 'placeholder@example.com',
      description: 'Comma-separated list of Tech Bytes Weekly digest subscribers',
    });

    // ---------------------------------------------------------------
    // 7. Lambda Functions (Python 3.12)
    // ---------------------------------------------------------------

    // Shared bundled asset — installs pip deps, copies source + config
    const lambdaCode = lambda.Code.fromAsset('../lambdas', {
      bundling: {
        image: lambda.Runtime.PYTHON_3_12.bundlingImage,
        command: [
          'bash',
          '-c',
          'pip install -r requirements.txt -t /asset-output && cp -r . /asset-output && cp -r /asset-input-config /asset-output/config',
        ],
        volumes: [
          { hostPath: `${process.cwd()}/../config`, containerPath: '/asset-input-config' },
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

      // Grant permission to publish custom CloudWatch metrics
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['cloudwatch:PutMetricData'],
          resources: ['*'],
          conditions: {
            StringEquals: { 'cloudwatch:namespace': 'TechBytes' },
          },
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
      email_digest: events.Schedule.expression('cron(0 9 ? * FRI *)'),
    };

    for (const { name, fn } of lambdaFunctions) {
      new events.Rule(this, `${pascalCase(name)}Schedule`, {
        schedule: schedules[name],
        targets: [new eventsTargets.LambdaFunction(fn)],
        description: `Scheduled trigger for ${name}`,
      });
    }

    // ---------------------------------------------------------------
    // 8b. Email Digest — additional permissions (S3 read, SES send, subscribers SSM)
    // ---------------------------------------------------------------
    const emailDigestEntry = lambdaFunctions.find(({ name }) => name === 'email_digest');
    if (emailDigestEntry) {
      const digestFn = emailDigestEntry.fn;

      // Grant read access to data/ prefix for reading latest JSON
      siteBucket.grantRead(digestFn, 'data/*');

      // Grant SES send permission
      digestFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['ses:SendEmail', 'ses:SendRawEmail'],
          resources: ['*'],
        }),
      );

      // Grant read access to subscribers SSM parameter
      digestFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['ssm:GetParameter'],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter${SUBSCRIBERS_PARAM}`,
          ],
        }),
      );
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
    // 11. SNS Topic for alerts
    // ---------------------------------------------------------------
    const alertsTopic = new sns.Topic(this, 'AlertsTopic', {
      topicName: 'TechBytesAlerts',
      displayName: 'Tech Bytes Alerts',
    });

    const alertEmailParam = new cdk.CfnParameter(this, 'AlertEmail', {
      type: 'String',
      default: '',
      description:
        'Email address for alert notifications. Leave empty to skip subscription (subscribe manually via AWS Console).',
    });

    const emailCondition = new cdk.CfnCondition(this, 'HasAlertEmail', {
      expression: cdk.Fn.conditionNot(
        cdk.Fn.conditionEquals(alertEmailParam.valueAsString, ''),
      ),
    });

    const emailSubscription = new sns.CfnSubscription(
      this,
      'AlertEmailSubscription',
      {
        topicArn: alertsTopic.topicArn,
        protocol: 'email',
        endpoint: alertEmailParam.valueAsString,
      },
    );
    emailSubscription.cfnOptions.condition = emailCondition;

    // ---------------------------------------------------------------
    // 12. Lambda error alarms
    // ---------------------------------------------------------------
    const snsAction = new cloudwatchActions.SnsAction(alertsTopic);

    for (const { name, fn } of lambdaFunctions) {
      const errorAlarm = new cloudwatch.Alarm(
        this,
        `${pascalCase(name)}ErrorAlarm`,
        {
          alarmName: `${name}-errors`,
          alarmDescription: `Lambda ${name} error count >= 1 in 1 hour`,
          metric: fn.metricErrors({
            period: cdk.Duration.hours(1),
            statistic: 'Sum',
          }),
          threshold: 1,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
      errorAlarm.addAlarmAction(snsAction);

      // ---------------------------------------------------------------
      // 13. Lambda duration alarms
      // ---------------------------------------------------------------
      const durationAlarm = new cloudwatch.Alarm(
        this,
        `${pascalCase(name)}DurationAlarm`,
        {
          alarmName: `${name}-duration`,
          alarmDescription: `Lambda ${name} max duration >= 4 min (close to 5 min timeout)`,
          metric: fn.metricDuration({
            period: cdk.Duration.hours(1),
            statistic: 'Maximum',
          }),
          threshold: 240_000,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
      durationAlarm.addAlarmAction(snsAction);
    }

    // ---------------------------------------------------------------
    // 14. CloudFront 5xx error rate alarm
    // ---------------------------------------------------------------
    const cloudFront5xxAlarm = new cloudwatch.Alarm(
      this,
      'CloudFront5xxAlarm',
      {
        alarmName: 'tech-bytes-cloudfront-5xx',
        alarmDescription:
          'CloudFront 5xx error rate >= 5% over 5 minutes',
        metric: new cloudwatch.Metric({
          namespace: 'AWS/CloudFront',
          metricName: '5xxErrorRate',
          dimensionsMap: {
            DistributionId: distribution.distributionId,
            Region: 'Global',
          },
          period: cdk.Duration.minutes(5),
          statistic: 'Average',
          region: 'us-east-1',
        }),
        threshold: 5,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    cloudFront5xxAlarm.addAlarmAction(snsAction);

    // ---------------------------------------------------------------
    // 15. AWS Budget ($10/month with 80% and 100% notifications)
    // ---------------------------------------------------------------
    new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: 'TechBytesMonthlyBudget',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: {
          amount: 10,
          unit: 'USD',
        },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold: 80,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [
            {
              subscriptionType: 'SNS',
              address: alertsTopic.topicArn,
            },
          ],
        },
        {
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold: 100,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [
            {
              subscriptionType: 'SNS',
              address: alertsTopic.topicArn,
            },
          ],
        },
      ],
    });

    // Grant AWS Budgets permission to publish to the SNS topic
    alertsTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('budgets.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [alertsTopic.topicArn],
      }),
    );

    // ---------------------------------------------------------------
    // 16. CloudWatch Dashboard
    // ---------------------------------------------------------------
    const METRIC_NAMESPACE = 'TechBytes';
    const dashboard = new cloudwatch.Dashboard(this, 'MonitoringDashboard', {
      dashboardName: 'TechBytes-Monitoring',
    });

    // --- Row 1: Lambda Invocations & Errors ---
    dashboard.addWidgets(
      ...lambdaFunctions.map(({ name, fn }) =>
        new cloudwatch.GraphWidget({
          title: `${pascalCase(name)} — Invocations & Errors`,
          width: 6,
          left: [
            fn.metricInvocations({ statistic: 'Sum', period: cdk.Duration.hours(1) }),
            fn.metricErrors({ statistic: 'Sum', period: cdk.Duration.hours(1) }),
            fn.metricThrottles({ statistic: 'Sum', period: cdk.Duration.hours(1) }),
          ],
        }),
      ),
    );

    // --- Row 2: Lambda Duration ---
    dashboard.addWidgets(
      ...lambdaFunctions.map(({ name, fn }) =>
        new cloudwatch.GraphWidget({
          title: `${pascalCase(name)} — Duration`,
          width: 6,
          left: [
            fn.metricDuration({ statistic: 'Average', period: cdk.Duration.hours(1) }),
            fn.metricDuration({ statistic: 'Maximum', period: cdk.Duration.hours(1) }),
          ],
        }),
      ),
    );

    // --- Row 3: Custom Metrics ---
    const customMetric = (metricName: string, label?: string): cloudwatch.Metric =>
      new cloudwatch.Metric({
        namespace: METRIC_NAMESPACE,
        metricName,
        statistic: 'Sum',
        period: cdk.Duration.days(1),
        label: label ?? metricName,
      });

    dashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: 'Items Processed (24h)',
        width: 8,
        metrics: [
          customMetric('StoriesProcessed', 'HN Stories'),
          customMetric('TechnologiesProcessed', 'Technologies'),
          customMetric('ReposProcessed', 'Repos'),
        ],
      }),
      new cloudwatch.SingleValueWidget({
        title: 'OpenAI API Calls (24h)',
        width: 8,
        metrics: [customMetric('OpenAISummarizations')],
      }),
      new cloudwatch.SingleValueWidget({
        title: 'S3 Uploads (24h)',
        width: 8,
        metrics: [
          customMetric('S3UploadsSucceeded', 'Succeeded'),
          customMetric('S3UploadsFailed', 'Failed'),
        ],
      }),
    );

    // --- Row 4: CloudFront ---
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'CloudFront — Requests & Bytes',
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/CloudFront',
            metricName: 'Requests',
            dimensionsMap: { DistributionId: distribution.distributionId, Region: 'Global' },
            statistic: 'Sum',
            period: cdk.Duration.hours(1),
            region: 'us-east-1',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/CloudFront',
            metricName: 'BytesDownloaded',
            dimensionsMap: { DistributionId: distribution.distributionId, Region: 'Global' },
            statistic: 'Sum',
            period: cdk.Duration.hours(1),
            region: 'us-east-1',
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'CloudFront — Error Rates',
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/CloudFront',
            metricName: '4xxErrorRate',
            dimensionsMap: { DistributionId: distribution.distributionId, Region: 'Global' },
            statistic: 'Average',
            period: cdk.Duration.hours(1),
            region: 'us-east-1',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/CloudFront',
            metricName: '5xxErrorRate',
            dimensionsMap: { DistributionId: distribution.distributionId, Region: 'Global' },
            statistic: 'Average',
            period: cdk.Duration.hours(1),
            region: 'us-east-1',
          }),
        ],
      }),
    );

    // --- Row 5: S3 Bucket ---
    dashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: 'S3 — Bucket Size',
        width: 12,
        metrics: [
          new cloudwatch.Metric({
            namespace: 'AWS/S3',
            metricName: 'BucketSizeBytes',
            dimensionsMap: {
              BucketName: siteBucket.bucketName,
              StorageType: 'StandardStorage',
            },
            statistic: 'Average',
            period: cdk.Duration.days(1),
          }),
        ],
      }),
      new cloudwatch.SingleValueWidget({
        title: 'S3 — Number of Objects',
        width: 12,
        metrics: [
          new cloudwatch.Metric({
            namespace: 'AWS/S3',
            metricName: 'NumberOfObjects',
            dimensionsMap: {
              BucketName: siteBucket.bucketName,
              StorageType: 'AllStorageTypes',
            },
            statistic: 'Average',
            period: cdk.Duration.days(1),
          }),
        ],
      }),
    );

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

    new cdk.CfnOutput(this, 'AlertsTopicArn', {
      value: alertsTopic.topicArn,
      description:
        'SNS topic ARN for alerts. Subscribe via: aws sns subscribe --topic-arn <arn> --protocol email --notification-endpoint your@email.com',
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
