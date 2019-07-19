from troposphere import elasticloadbalancing as elb
from troposphere import Equals, GetAtt, If, Join, Not, Output, Parameter, Ref

from .common import environments
from .security_groups import aws_elb_security_group
from .template import template
from .vpc import public_a_subnet, public_b_subnet

web_worker_health_check = Ref(
    template.add_parameter(
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
)

# Web load balancer

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
        tcp_health_check_condition, Equals(web_worker_health_check, "")
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
            InstanceProtocol=If(acm_cert_condition, "HTTP", "TCP"),
            InstancePort=80,
            Protocol=If(acm_cert_condition, "HTTPS", "TCP"),
            SSLCertificateId=If(acm_cert_condition, acm_cert_arn, Ref("AWS::NoValue")),
        ),
    ]

    load_balancer = elb.LoadBalancer(
        "LoadBalancer%s" % environment.title(),
        template=template,
        Subnets=[Ref(public_a_subnet), Ref(public_b_subnet)],
        SecurityGroups=[Ref(aws_elb_security_group)],
        Listeners=listeners,
        HealthCheck=elb.HealthCheck(
            Target=If(
                tcp_health_check_condition,
                "TCP:80",
                Join("", ["HTTPS:80", web_worker_health_check]),
            ),
            HealthyThreshold="2",
            UnhealthyThreshold="2",
            Interval="10",
            Timeout="9",
        ),
        Instances=[],  # will be added by fabulaws
        CrossZone=True,
    )

    template.add_output(
        Output(
            "LoadBalancer%sDNSName" % environment.title(),
            Description="Loadbalancer DNS",
            Value=GetAtt(load_balancer, "DNSName"),
        )
    )
