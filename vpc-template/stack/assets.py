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
    Private,
    PublicAccessBlockConfiguration,
    ServerSideEncryptionByDefault,
    ServerSideEncryptionRule,
    VersioningConfiguration,
)

from .common import arn_prefix, environments
from .domain import domain_name, domain_name_alternates, no_alt_domains
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
    CorsConfiguration=CorsConfiguration(
        CorsRules=[
            CorsRules(
                AllowedOrigins=Split(
                    ";",
                    Join(
                        "",
                        [
                            "https://",
                            domain_name,
                            If(
                                no_alt_domains,
                                # if we don't have any alternate domains, return an empty string
                                "",
                                # otherwise, return the ';https://' that will be needed by the first domain
                                ";https://",
                            ),
                            # then, add all the alternate domains, joined together with ';https://'
                            Join(";https://", domain_name_alternates),
                            # now that we have a string of origins separated by ';',
                            # Split() is used to make it into a list again
                        ],
                    ),
                ),
                AllowedMethods=["POST", "PUT", "HEAD", "GET"],
                AllowedHeaders=["*"],
            )
        ]
    ),
)

assets_buckets = []
private_buckets = []

for environment in environments:
    # Create an S3 bucket that holds statics and media
    assets_bucket = template.add_resource(
        Bucket(
            "AssetsBucket%s" % environment.title(),
            AccessControl=Private,  # Objects can still be made public
            **common_bucket_conf,
        )
    )
    # Output S3 asset bucket name
    template.add_output(
        Output(
            "AssetsBucket%sDomainName" % environment.title(),
            Description="Assets bucket domain name (%s)" % environment,
            Value=GetAtt(assets_bucket, "DomainName"),
        )
    )
    assets_buckets.append(assets_bucket)
    # Create an S3 bucket that holds user uploads or other non-public files
    private_bucket = template.add_resource(
        Bucket(
            "PrivateBucket%s" % environment.title(),
            AccessControl=Private,
            PublicAccessBlockConfiguration=PublicAccessBlockConfiguration(
                BlockPublicAcls=True,
                BlockPublicPolicy=True,
                IgnorePublicAcls=True,
                RestrictPublicBuckets=True,
            ),
            **common_bucket_conf,
        )
    )
    # Output S3 asset bucket name
    template.add_output(
        Output(
            "PrivateBucket%sDomainName" % environment.title(),
            Description="Private bucket domain name (%s)" % environment,
            Value=GetAtt(private_bucket, "DomainName"),
        )
    )
    private_buckets.append(private_bucket)


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
                for bucket in assets_buckets + private_buckets
            ],
            *[
                dict(
                    Effect="Allow",
                    Action=["s3:*"],
                    Resource=Join("", [arn_prefix, ":s3:::", Ref(bucket), "/*"]),
                )
                for bucket in assets_buckets + private_buckets
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

for environment in environments:
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
                        DomainName=GetAtt(assets_bucket, "DomainName"),
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
