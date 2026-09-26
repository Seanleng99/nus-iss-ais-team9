# AWS Account Migration

Source account: `902552928492`. Destination account: `862124275471`.
Deployment Region: `ap-southeast-1`. Domain: `ai-financial-wellness-coach.click`.

The production cutover completed September 26, 2026 (Singapore time). The four
users have since been imported to the new account's Cognito pool with required
password resets, after the owner changed the earlier decision to keep old sign-in.
One user confirmed their prior records. The owner explicitly waived retaining
the old Cognito pool, old backups, historical ECR images, and CloudWatch logs
while the other three complete password resets. Keep the old DNS hosted zone
until at least September 28, 2026, 02:20:49 SGT, 48 hours after registrar
delegation changed. Deployment scripts default to the destination account; pass
`-AccountId 902552928492` explicitly for a source-account diagnostic script.

## Production cutover status

- Route 53 domain registration and registrar delegation are in the destination
  account. Registrar operation `befbd4a7-a17f-47a4-8c9b-86b31dae1fe9`
  succeeded. Name servers are `ns-498.awsdns-62.com`,
  `ns-908.awsdns-49.net`, `ns-1813.awsdns-34.co.uk`, and
  `ns-1468.awsdns-55.org`. Destination zone `Z053270513FALP98M94L0`
  and source zone `Z082992016ATT9Y4OFS9V` both alias the apex to new
  CloudFront distribution `E1I8G8SUBPQYYM` (`d1chx1r2f68pcy.cloudfront.net`).
  Old distribution `E10L5HJWD7L257` is disabled and retained.
- `https://ai-financial-wellness-coach.click/` and `/health` return HTTP 200.
  The production OIDC metadata now advertises the destination issuer
  `https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_UwY4lW61s`;
  the application stack uses new client `1ef4ecte8mqse938jr5m1fgb44` and
  maps each new `custom:legacy_sub` to the old data-owner issuer. The four-user
  import job `import-qzxgvzQyoR` succeeded with zero failures or skips. One
  user reset their password, signed in, and confirmed their prior financial
  data is visible; Cognito shows one `CONFIRMED` and three `RESET_REQUIRED`.
  The other three users still need to reset passwords and verify records; this
  does not block source pool deletion under the owner's revised direction. The
  temporary Cognito import IAM role was removed after the successful import.
- The old application and GitHub OIDC CloudFormation stacks were deleted. All
  three old ECS services are gone; the old RDS instance is stopped. Stopping the
  backend froze application writes before the final snapshot. New AI, backend,
  and frontend ECS services are healthy at 1/1 each. The old foundation stack
  remains for the DNS cache transition and still owns the old RDS instance,
  Cognito client, ECR repositories, CloudFront distribution, and DNS records.
- All old manual RDS snapshots, including
  `ai-financial-wellness-coach-final-20260926` and its shareable copy, were
  deleted after the destination private final copy
  `ai-financial-wellness-coach-final-copy-20260926` became available.
  Destination DB `ai-financial-wellness-coach-final` is restored, and the
  application stack points to it. Its RDS-managed secret is scoped exactly in
  the ECS execution role. The final restore matches the frozen source by row
  count and SHA-256 content fingerprint for all 12 PostgreSQL tables. After
  both private copies completed, temporary cross-account RDS snapshot restore
  attributes and destination KMS key-policy grants were revoked.
- GitHub Actions deploy and frontend URL variables point to account
  `862124275471` and the production apex. The two destination knowledge bases
  ingested their source data and passed retrieval checks.
- Old Bedrock knowledge bases, S3 vector buckets/indexes, and source corpus
  bucket were deleted after the destination corpus and retrieval checks passed.
  The migration-only source KMS key is scheduled for deletion October 3, 2026,
  09:07:54 SGT; its cross-account policy grants were revoked. A temporary log
  archive in the destination account was removed under the owner's revised
  retention preference; the old log groups remain until foundation deletion.
- Do not delete the old foundation stack or hosted zone before September 28,
  2026, 02:20:49 SGT. Old recursive DNS caches may still follow the source zone.
  After that time, delete the foundation stack and old hosted zone, then manually
  delete the retained old Cognito pool and any RDS snapshot created by stack
  deletion. The owner chose not to keep historical source ECR images. Check for
  remaining source-account resources and charges.

## Verified source inventory (September 25, 2026)

- Route 53 registration is active and eligible for an internal account transfer.
  Registration date: August 30, 2026; expiration: August 30, 2027.
  Public hosted zone `Z082992016ATT9Y4OFS9V` has six records, including
  application and origin aliases and two ACM validation CNAMEs. DNSSEC is off.
  The internal transfer to `862124275471` completed on September 25, 2026.
  Route 53 showed the incoming request as **Successful**, and the domain appears
  under Registered domains in the destination account. Its four name servers
  initially remained the same. Domain registration transfer did not move that
  hosted zone; registrar delegation changed to the destination zone at cutover.
- RDS PostgreSQL instance `ai-financial-wellness-coach-demo` is available in
  Singapore with 20 GiB allocated storage. It is encrypted with the AWS-managed
  `aws/rds` key. There were no manual snapshots. A manual safety snapshot named
  `ai-financial-wellness-coach-pre-migration-20260925` is `available` in the
  source account. A second copy named
  `ai-financial-wellness-coach-pre-migration-shareable-20260925`, encrypted under
  source customer-managed key `alias/ai-financial-wellness-coach-snapshot-share`,
  is also `available`. It temporarily granted account `862124275471` restore
  access and the required KMS operations; those grants have since been revoked.
  The destination account has
  started a private copy named
  `ai-financial-wellness-coach-pre-migration-copy-20260926`, encrypted with its
  own `aws/rds` key. The destination copy reached `available` with 100% progress.
  This preliminary backup remains available. The final backup and restore are
  described in the production cutover status above.
- Cognito pool `ap-southeast-1_Z1zO5LOAq` contains four users. The app stores
  their Cognito issuer and `sub` in `users.owner_issuer` and
  `users.owner_subject`. Those values change with a new pool. Its only app client
  currently allows SRP and refresh-token authentication. Password-preserving
  migration would require a temporary password-authentication client for the
  old pool and a migration trigger for the new pool. The owner declined that
  approach and later approved a password-reset import. The old pool and app
  client were not modified to enable password migration.
- Two Bedrock knowledge bases are available: Education `X2BXBRYX2X` and
  Policy `MLOCSOIFML`. Both use Cohere Embed Multilingual v3, S3 source data,
  and separate S3 Vector buckets and indexes. The source S3 bucket has 18 current
  objects totaling 58,282 bytes; bucket versioning is not enabled.
  The governed source content and indexes were recreated in the new account.
- The source account has three active CloudFormation stacks: foundation,
  application, and GitHub OIDC. It also has three immutable ECR repositories
  for the AI, backend, and frontend images.
- The 18 S3 corpus objects were staged in a local tar archive and verified with
  SHA-256 `d90708103da4bec2cbf11b89e2f4bf414f62c1bc6ad0d1cfd8affd590305c600`.
  The destination CloudShell upload matched the same hash. The files were copied
  into private bucket `nus-iss-ais-team9-rag-862124275471-ap-southeast-1`, with
  public access blocked and versioning enabled. The destination lists 18 objects
  totaling 58,282 bytes, matching the source inventory. New knowledge bases
  and vector indexes are Education `CUCOPYHG5P`/source `BXVNX4OULE` and Policy
  `QWYTV35QBC`/source `WH5OQ7UAPT`. The Cohere Embed Multilingual v3 agreement
  was accepted after owner approval. Policy indexed all three documents, and
  Education indexed all six after retrying one transient error. Retrieval tests
  returned results from both knowledge bases.

An additional scan of all 17 enabled Regions found CloudFormation stacks, RDS,
ECS, ECR, and CloudWatch log groups only in `ap-southeast-1`; no EC2 instances
or Lambda functions were found in those Regions. The global and project-specific
resources listed above have since been partially removed. This scan does not
cover every AWS service, untagged resource, billing item, or retained
CloudFormation resource, so do not claim the source account is empty. The owner
does not require retention of the old CloudWatch logs.

## Deployment details

- The destination public hosted zone is `Z053270513FALP98M94L0` with both new
  ACM validation records. The registrar now delegates to this zone. The destination
  zone's name servers are `ns-498.awsdns-62.com`, `ns-908.awsdns-49.net`,
  `ns-1813.awsdns-34.co.uk`, and `ns-1468.awsdns-55.org`.
- Both destination ACM certificates are issued: viewer
  `arn:aws:acm:us-east-1:862124275471:certificate/19b3c441-9c21-4850-8b9e-9f2df3a3adf2`
  and origin
  `arn:aws:acm:ap-southeast-1:862124275471:certificate/34ce42d4-321a-4262-a56e-d712649e36e5`.
- Local AWS CLI profiles `coach-old` and `coach-new` use short-lived AWS login
  sessions. Verify `sts get-caller-identity` before account mutations. Docker
  Desktop and GitHub CLI authentication for `Seanleng99` are working.
- The destination foundation, ECS application, and GitHub OIDC stacks are
  deployed. The final source snapshot restored the production RDS instance;
  its new-account RDS-managed secret is active and the ECS execution role is
  scoped to that exact secret. GitHub demo variables and the smoke-test secret
  target account `862124275471`.
- The destination CloudFront distribution serves
  `https://stage.ai-financial-wellness-coach.click/` through the separate
  `origin-app.ai-financial-wellness-coach.click` ALB hostname. Both the staging
  frontend and `/health` returned HTTP 200; the CloudFront origin protocol is
  `https-only`. ACM issued the staging viewer certificate
  `arn:aws:acm:us-east-1:862124275471:certificate/7d0cb9fc-14f2-493a-aa43-eff37384a356`
  and the staging origin certificate
  `arn:aws:acm:ap-southeast-1:862124275471:certificate/a88be948-3792-4357-ac08-54456a2778cc`.
  Production apex DNS now targets the destination distribution, and the old
  distribution is disabled.

## Migration and remaining verification

1. Inventory CloudFormation stacks and resources, S3 buckets and object versions,
   RDS snapshots, Cognito users/groups, Bedrock knowledge bases and vector stores,
   ECR images, CloudWatch logs, Secrets Manager, ACM certificates, IAM/OIDC roles,
   Route 53 zones and records, and resources in every enabled Region. Record data
   retention requirements and produce backups with restore checks.
2. Completed: create a final RDS manual snapshot after writes are paused. Because the source
   database uses `aws/rds`, copy that snapshot under a customer-managed KMS key,
   grant the destination account the required snapshot and key access, copy the
   shared snapshot into the destination account, and restore it there. Establish
   a destination-managed database credential. The foundation template now takes
   `DatabaseSnapshotIdentifier` and `DatabaseInstanceIdentifier`. When replacing
   the preliminary restore with the final snapshot, use a new DB instance ID
   because CloudFormation cannot replace a DB instance under the same fixed name.
3. Completed: import four old Cognito profiles into destination pool
   `ap-southeast-1_UwY4lW61s`, with verified emails and an immutable
   `custom:legacy_sub` containing their old subject IDs. Their old passwords
   and hashes cannot be exported from Cognito. The new pool requires each user
   to reset a password. The backend validates new-pool ID tokens, then maps
   the immutable legacy subject to existing database ownership. Test all four
   users' sign-in and records. One user has completed this check; the owner
   authorized removal of the old pool without waiting for the other three.
4. Completed: copy and verify both governed S3 corpora, including metadata sidecars and any
   object versions that must be retained. Recreate Bedrock knowledge bases and
   S3 vector indexes with equivalent configuration, ingest, then run the
   repository's governance audits and application retrieval tests.
5. Deploy the application, certificates, GitHub OIDC roles, and CI/CD variables
   in the destination account. Verify database migrations, login, owner isolation,
   RAG provenance, alarms, smoke tests, and HTTPS edge restrictions.
6. Completed: disable the old CloudFront distribution, move its apex alias to
   the destination distribution, point both hosted zones at the new distribution,
   and update registrar name servers to the destination zone. One user verified
   prior records. Keep the old zone until September 28, 2026, 02:20:49 SGT.
7. Completed before the DNS transition deadline: delete old application and
   GitHub OIDC stacks, manual RDS snapshots, Bedrock knowledge bases, vector
   stores, and source corpus bucket; schedule the migration KMS key for
   deletion. After the deadline, delete the source foundation stack and hosted
   zone. CloudFormation retains the old Cognito pool and snapshots the old RDS
   instance; remove those deliberately. Verify billing and account-wide
   resources before closing the source account.

## AWS references

- [Transfer domain between AWS accounts](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/domain-transfer-between-aws-accounts.html)
- [Migrate a hosted zone](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zones-migrating.html)
- [Copy an encrypted RDS snapshot](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_CopySnapshot.html)
- [Import Cognito users](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-import-users.html)
- [Migrate Cognito users at sign-in](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-import-using-lambda.html)
- [RDS CloudFormation snapshot restore](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-rds-dbinstance.html)
