#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { TechBytesStack } from '../lib/tech-bytes-stack';

const app = new cdk.App();

// Account falls back to the known deployment account so `cdk synth` works in
// CI (preview.yml) where no AWS credentials are configured. The hosted-zone
// lookup is served from the committed cdk.context.json cache, so no live AWS
// call is needed at synth time.
const ACCOUNT = process.env.CDK_DEFAULT_ACCOUNT ?? '333674319299';

new TechBytesStack(app, 'TechBytesStack', {
  env: {
    account: ACCOUNT,
    region: 'ap-southeast-1',
  },
});
