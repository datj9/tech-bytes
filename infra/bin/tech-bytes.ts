#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { TechBytesStack } from '../lib/tech-bytes-stack';

const app = new cdk.App();

new TechBytesStack(app, 'TechBytesStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'ap-southeast-1',
  },
});
