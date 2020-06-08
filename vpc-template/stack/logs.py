from troposphere import AWS_REGION, Join, Ref, iam, logs

from .common import arn_prefix
from .template import template

log_group = logs.LogGroup(
    "LogGroup",
    template=template,
    RetentionInDays=731,  # 2 years
    DeletionPolicy="Retain",
)


logging_policy = iam.Policy(
    PolicyName="LoggingPolicy",
    PolicyDocument=dict(
        Statement=[
            dict(
                Effect="Allow",
                Action=["logs:Create*", "logs:PutLogEvents"],
                Resource=Join(
                    "",
                    [
                        arn_prefix,
                        ":logs:",
                        Ref(AWS_REGION),
                        ":*:log-group:",
                        Ref(log_group),  # allow logging to this log group only
                        ":*",
                    ],
                ),
            )
        ]
    ),
)
