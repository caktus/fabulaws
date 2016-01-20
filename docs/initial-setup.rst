Setting up a project to be deployed with Fabulaws
=================================================

AWS Configuration
-----------------

Some configuration within the AWS console is necessary to begin using FabulAWS:

IAM User
++++++++

First, you'll need to create credentials via IAM that have permissions to create
servers in EC2 and manage autoscaling groups and load balancers.

Security Groups
+++++++++++++++

You'll also need the following security groups. These can be renamed for your
project and updated in `fabulaws-config.yml`.

* **myproject-sg**
   * TCP port 22 from 0.0.0.0/0
* **myproject-cache-sg**
   * TCP port 11211 from myproject-web-sg
   * TCP port 11211 from myproject-worker-sg
* **myproject-db-sg**
   * TCP port 5432 from myproject-web-sg
   * TCP port 5432 from myproject-worker-sg
   * TCP port 5432 from myproject-db-sg
* **myproject-queue-sg**
   * TCP port 5672 from myproject-web-sg
   * TCP port 5672 from myproject-worker-sg
* **myproject-session-sg**
   * TCP port 6379 from myproject-web-sg
   * TCP port 6379 from myproject-worker-sg
* **myproject-web-sg**
   * TCP port 80 from amazon-elb-sg
   * TCP port 443 from amazon-elb-sg
* **myproject-worker-sg**
   * (used only as a source - requires no additional firewall rules)

Load Balancer
+++++++++++++

You will need to create a load balancer for your instances, at least one for
each environment. Note that multiple load balancers can be used if the site
serves different domains (though a single load balancer can be used for a
wildcard SSL certificate). Use the following parameters as a guide:

* Choose a name and set it in ``fabulaws-config.yml``
* Ports 80 and 443 should be mapped to 80 and 443 on the instances
* Backend authentication and stickiness should be disabled
* The zones chosen should match those in ``fabulaws-config.yml`` (typically 2)
* Until FabulAWS is upgraded to support VPC, Classic-style load balancers should
  be used
* Configure a custom SSL certificate, if desired.

After the load balancer is created, you can set the domain name for the
associated environment ``fabulaws-config.yml`` to your custom domain or the
default domain for the load balancer.

Auto Scaling Group
++++++++++++++++++

You will also need to create one auto scaling group per envrionment, with the
following parameters:

* Choose a name and set it in ``fabulaws-config.yml``
* Choose a dummy launch config and set it to 0 instances to start
* Select Advanced, choose your load balancer, and select the ELB health check
* Choose the same availability zones as for your load balancer
* You don't need to configure scaling policies yet, but these will need to be
  set eventually based on experience

