from itertools import chain

from troposphere import (
    AWS_REGION,
    And,
    Equals,
    GetAtt,
    If,
    Join,
    Not,
    Output,
    Ref,
    Split,
    iam,
)
from troposphere.certificatemanager import Certificate, DomainValidationOption
from troposphere.cloudfront import (
    DefaultCacheBehavior,
    Distribution,
    DistributionConfig,
    ForwardedValues,
    Origin,
    S3OriginConfig,
    ViewerCertificate,
)
from troposphere.s3 import (
    Bucket,
    BucketEncryption,
    CorsConfiguration,
    CorsRules,
    LogDeliveryWrite,
    LoggingConfiguration,
    Private,
    PublicAccessBlockConfiguration,
    ServerSideEncryptionByDefault,
    ServerSideEncryptionRule,
    VersioningConfiguration,
)

from .common import arn_prefix, environments
from .domain import domains
from .template import template
from .utils import ParameterWithDefaults as Parameter

use_aes256_encryption = template.add_parameter(
    Parameter(
        "AssetsUseAES256Encryption",
        Description="Whether or not to use server side encryption for S3 buckets. "
        "When true, AES256 encryption is enabled for all asset buckets.",
        Type="String",
        AllowedValues=["true", "false"],
        Default="true",
    ),
    group="Static Media",
    label="Enable AES256 Encryption",
)
use_aes256_encryption_cond = "AssetsUseS3EncryptionCondition"
template.add_condition(
    use_aes256_encryption_cond, Equals(Ref(use_aes256_encryption), "true")
)

common_bucket_conf = dict(
    BucketEncryption=BucketEncryption(
        ServerSideEncryptionConfiguration=If(
            use_aes256_encryption_cond,
            [
                ServerSideEncryptionRule(
                    ServerSideEncryptionByDefault=ServerSideEncryptionByDefault(
                        SSEAlgorithm="AES256"
                    )
                )
            ],
            [ServerSideEncryptionRule()],
        )
    ),
    VersioningConfiguration=VersioningConfiguration(Status="Enabled"),
    DeletionPolicy="Retain",
)

buckets = {env: {} for env in environments}


def add_bucket(environment, name, include_output=False, logs_bucket=None, **extra_kwargs):
    extra_kwargs.update(common_bucket_conf)
    if logs_bucket:
        extra_kwargs["LoggingConfiguration"] = LoggingConfiguration(
            DestinationBucketName=Ref(logs_bucket),
            LogFilePrefix="%s%s/" % (environment.title(), name),
        )
    if "AccessControl" not in extra_kwargs:
        extra_kwargs["AccessControl"] = Private  # Objects can still be made public
    bucket = template.add_resource(
        Bucket(
            "%sBucket%s" % (name, environment.title()),
            **extra_kwargs,
        )
    )
    if environment:
        buckets[environment][name] = bucket
    if include_output:
        # Output S3 asset bucket name
        template.add_output(
            Output(
                "%sBucket%sDomainName" % (name, environment.title()),
                Description="%s bucket domain name (%s)" % (name, environment),
                Value=GetAtt(bucket, "DomainName"),
            )
        )
    return bucket


private_access_block = PublicAccessBlockConfiguration(
    BlockPublicAcls=True,
    BlockPublicPolicy=True,
    IgnorePublicAcls=True,
    RestrictPublicBuckets=True,
)

s3_logs_bucket = add_bucket(
    "",  # empty environment name
    "BucketLogs",
    PublicAccessBlockConfiguration=private_access_block,
    AccessControl=LogDeliveryWrite,
)

elb_logs_bucket = add_bucket(
    "",  # empty environment name
    "ElbLogs",
    logs_bucket=s3_logs_bucket,
    PublicAccessBlockConfiguration=private_access_block,
)

for environment in environments:
    cors_configuration = CorsConfiguration(
        CorsRules=[
            CorsRules(
                AllowedOrigins=Split(
                    ";",
                    Join(
                        "",
                        [
                            # prepend "https://"
                            "https://",
                            # join all domains for this environment with ';https://'
                            Join(";https://", domains[environment]),
                            # now that we have a string of origins separated by ';',
                            # Split() is used to make it into a list again
                        ],
                    ),
                ),
                AllowedMethods=["POST", "PUT", "HEAD", "GET"],
                AllowedHeaders=["*"],
            )
        ]
    )
    # no logging for public assets (no protected information in this bucket)
    add_bucket(environment, "Assets", CorsConfiguration=cors_configuration, include_output=True)
    add_bucket(
        environment,
        "Private",
        include_output=True,
        logs_bucket=s3_logs_bucket,
        CorsConfiguration=cors_configuration,
        PublicAccessBlockConfiguration=private_access_block,
    )
    add_bucket(environment, "Backups", logs_bucket=s3_logs_bucket, PublicAccessBlockConfiguration=private_access_block)


# central asset management policy for use in instance roles
assets_management_policy = iam.Policy(
    PolicyName="AssetsManagementPolicy",
    PolicyDocument=dict(
        Statement=[
            *[
                dict(
                    Effect="Allow",
                    Action=["s3:ListBucket"],
                    Resource=Join("", [arn_prefix, ":s3:::", Ref(bucket)]),
                )
                for bucket in chain(*[bucket_map.values() for _, bucket_map in buckets.items()])
            ],
            *[
                dict(
                    Effect="Allow",
                    Action=["s3:*"],
                    Resource=Join("", [arn_prefix, ":s3:::", Ref(bucket), "/*"]),
                )
                for bucket in chain(*[bucket_map.values() for _, bucket_map in buckets.items()])
            ],
        ]
    ),
)

distributions = []

assets_use_cloudfront = template.add_parameter(
    Parameter(
        "AssetsUseCloudFront",
        Description="Whether or not to create a CloudFront distribution tied to the S3 assets bucket.",
        Type="String",
        AllowedValues=["true", "false"],
        Default="true",
    ),
    group="Static Media",
    label="Enable CloudFront",
)
assets_use_cloudfront_condition = "AssetsUseCloudFrontCondition"
template.add_condition(
    assets_use_cloudfront_condition, Equals(Ref(assets_use_cloudfront), "true")
)

assets_cloudfront_domain = template.add_parameter(
    Parameter(
        "AssetsCloudFrontDomain",
        Description="A custom domain name (CNAME) for your CloudFront distribution, e.g., "
        '"static.example.com".',
        Type="String",
        Default="",
    ),
    group="Static Media",
    label="CloudFront Custom Domain",
)
assets_custom_domain_condition = "AssetsCloudFrontDomainCondition"
template.add_condition(
    assets_custom_domain_condition, Not(Equals(Ref(assets_cloudfront_domain), ""))
)

# Currently, you can specify only certificates that are in the US East (N. Virginia) region.
# http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-cloudfront-distributionconfig-viewercertificate.html
assets_custom_domain_and_us_east_1_condition = (
    "AssetsCloudFrontDomainAndUsEast1Condition"
)
template.add_condition(
    assets_custom_domain_and_us_east_1_condition,
    And(
        Not(Equals(Ref(assets_cloudfront_domain), "")),
        Equals(Ref(AWS_REGION), "us-east-1"),
    ),
)

assets_certificate = template.add_resource(
    Certificate(
        "AssetsCertificate",
        Condition=assets_custom_domain_and_us_east_1_condition,
        DomainName=Ref(assets_cloudfront_domain),
        DomainValidationOptions=[
            DomainValidationOption(
                DomainName=Ref(assets_cloudfront_domain),
                ValidationDomain=Ref(assets_cloudfront_domain),
            )
        ],
    )
)

assets_certificate_arn = template.add_parameter(
    Parameter(
        "AssetsCloudFrontCertArn",
        Description="If (1) you specified a custom static media domain, (2) your stack is NOT in the us-east-1 "
        "region, and (3) you wish to serve static media over HTTPS, you must manually create an "
        "ACM certificate in the us-east-1 region and provide its ARN here.",
        Type="String",
    ),
    group="Static Media",
    label="CloudFront SSL Certificate ARN",
)
assets_certificate_arn_condition = "AssetsCloudFrontCertArnCondition"
template.add_condition(
    assets_certificate_arn_condition, Not(Equals(Ref(assets_certificate_arn), ""))
)

for environment, bucket_map in buckets.items():
    # Create a CloudFront CDN distribution
    distribution = template.add_resource(
        Distribution(
            "AssetsDistribution%s" % environment.title(),
            Condition=assets_use_cloudfront_condition,
            DistributionConfig=DistributionConfig(
                Aliases=If(
                    assets_custom_domain_condition,
                    [Ref(assets_cloudfront_domain)],
                    Ref("AWS::NoValue"),
                ),
                # use the ACM certificate we created (if any), otherwise fall back to the manually-supplied
                # ARN (if any)
                ViewerCertificate=If(
                    assets_custom_domain_and_us_east_1_condition,
                    ViewerCertificate(
                        AcmCertificateArn=Ref(assets_certificate),
                        SslSupportMethod="sni-only",
                    ),
                    If(
                        assets_certificate_arn_condition,
                        ViewerCertificate(
                            AcmCertificateArn=Ref(assets_certificate_arn),
                            SslSupportMethod="sni-only",
                        ),
                        Ref("AWS::NoValue"),
                    ),
                ),
                Origins=[
                    Origin(
                        Id="Assets",
                        DomainName=GetAtt(bucket_map["Assets"], "DomainName"),
                        S3OriginConfig=S3OriginConfig(OriginAccessIdentity=""),
                    )
                ],
                DefaultCacheBehavior=DefaultCacheBehavior(
                    TargetOriginId="Assets",
                    ForwardedValues=ForwardedValues(
                        # Cache results *should* vary based on querystring (e.g., 'style.css?v=3')
                        QueryString=True,
                        # make sure headers needed by CORS policy above get through to S3
                        # http://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/header-caching.html#header-caching-web-cors
                        Headers=[
                            "Origin",
                            "Access-Control-Request-Headers",
                            "Access-Control-Request-Method",
                        ],
                    ),
                    ViewerProtocolPolicy="allow-all",
                ),
                Enabled=True,
            ),
        )
    )

    # Output CloudFront url
    template.add_output(
        Output(
            "AssetsDistribution%sDomainName" % environment.title(),
            Description="The assets bucket CDN domain name (%s)" % environment,
            Value=GetAtt(distribution, "DomainName"),
            Condition=assets_use_cloudfront_condition,
        )
    )
    distributions.append(distribution)
