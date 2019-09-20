from troposphere import elasticloadbalancing as elb, s3
from troposphere import Equals, GetAtt, If, Join, Not, Output, Parameter, Ref

from .assets import buckets
from .common import arn_prefix, environments
from .security_groups import aws_elb_security_group
from .template import template
from .vpc import public_subnet_a, public_subnet_b

web_worker_health_check = template.add_parameter(
    Parameter(
        "WebWorkerHealthCheck",
        Description='Web worker health check URL path, e.g., "/health-check"; '
        "will default to TCP-only health check if left blank",
        Type="String",
        Default="",
    ),
    group="Load Balancer",
    label="Health Check URL",
)

elb_account_id = template.add_parameter(
    Parameter(
        "ElbAccountID",
        Description="AWS account ID for ELBs for your region. See: "
                    "https://docs.aws.amazon.com/elasticloadbalancing/latest/classic/enable-access-logs.html",
        Type="String",
        Default="",
    ),
    group="Load Balancer",
    label="Elastic Load Balancing Account ID",
)

# Web load balancers
load_balancers = {}

for environment in environments:
    acm_cert_arn = Ref(
        template.add_parameter(
            Parameter(
                "AcmCertArn%s" % environment.title(),
                Description="ARN of the AWS Certificate Manager certificate (optional). If omitted, TCP "
                "connections will be passed directly to the backend instances on port 443.",
                Type="String",
                Default="",
            ),
            group="Load Balancer",
            label="ACM Certificate ARN (%s)" % environment,
        )
    )

    tcp_health_check_condition = "TcpHealthCheck%s" % environment.title()
    template.add_condition(
        tcp_health_check_condition, Equals(Ref(web_worker_health_check), "")
    )

    acm_cert_condition = "AcmCertCondition%s" % environment.title()
    template.add_condition(acm_cert_condition, Not(Equals(acm_cert_arn, "")))

    listeners = [
        elb.Listener(
            LoadBalancerPort=80,
            InstanceProtocol="HTTP",
            InstancePort=80,
            Protocol="HTTP",
        ),
        # If ACM is enabled, use the certificate here, otherwise pass TCP connections directly
        elb.Listener(
            LoadBalancerPort=443,
            InstanceProtocol=If(acm_cert_condition, "HTTPS", "TCP"),
            InstancePort=443,
            Protocol=If(acm_cert_condition, "HTTPS", "TCP"),
            SSLCertificateId=If(acm_cert_condition, acm_cert_arn, Ref("AWS::NoValue")),
        ),
    ]

    bucket_policy = s3.BucketPolicy(
        "ElbLogsBucketPolicy%s" % environment.title(),
        template=template,
        Bucket=Ref(buckets[environment]["ElbLogs"]),
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": Join("", ["arn:aws:iam::", Ref(elb_account_id), ":root"]),
                    },
                    "Action": "s3:PutObject",
                    "Resource": Join("", [arn_prefix, ":s3:::", Ref(buckets[environment]["ElbLogs"]), "/*"]),
                }
            ]
        }
    )

    load_balancers[environment] = elb.LoadBalancer(
        "Elb%s" % environment.title(),
        template=template,
        Subnets=[Ref(public_subnet_a), Ref(public_subnet_b)],
        SecurityGroups=[Ref(aws_elb_security_group)],
        Listeners=listeners,
        HealthCheck=elb.HealthCheck(
            Target=If(
                tcp_health_check_condition,
                "TCP:80",
                Join("", ["HTTPS:443", Ref(web_worker_health_check)]),
            ),
            HealthyThreshold="2",
            UnhealthyThreshold="2",
            Interval="10",
            Timeout="9",
        ),
        AccessLoggingPolicy=elb.AccessLoggingPolicy(
            EmitInterval=60,
            Enabled=True,
            S3BucketName=Ref(buckets[environment]["ElbLogs"])
        ),
        Instances=[],  # will be added by fabulaws
        CrossZone=True,
        DependsOn=bucket_policy,
    )

    template.add_output(
        Output(
            "Elb%sDnsName" % environment.title(),
            Description="Loadbalancer DNS",
            Value=GetAtt(load_balancers[environment], "DNSName"),
        )
    )
