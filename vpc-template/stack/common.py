from troposphere import AWS_REGION, Equals, If, Ref

from .template import template

environments = ["staging", "production"]

dont_create_value = "(none)"

in_govcloud_region = "InGovCloudRegion"
template.add_condition(in_govcloud_region, Equals(Ref(AWS_REGION), "us-gov-west-1"))
arn_prefix = If(in_govcloud_region, "arn:aws-us-gov", "arn:aws")
