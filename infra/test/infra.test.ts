import * as cdk from 'aws-cdk-lib/core';
import { Template } from 'aws-cdk-lib/assertions';
import { TechBytesStack } from '../lib/tech-bytes-stack';

test('Stack creates S3 bucket', () => {
  const app = new cdk.App();
  const stack = new TechBytesStack(app, 'TestStack', {
    env: { account: '123456789012', region: 'ap-southeast-1' },
  });
  const template = Template.fromStack(stack);

  template.resourceCountIs('AWS::S3::Bucket', 2); // site bucket + deployment bucket
});
