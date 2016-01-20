Server Architecture
===================

Prior to creating any new servers or deploying new code using FabulAWS, it's
helpful to have an overall understand of the different components of the
server architecture.

FabulAWS creates 5 different types of servers, plus an Amazon Elastic Load
Balancer.

Load Balancer
-------------
Load balancers are created and managed in the AWS Management Console. The
the following ports need to be configured:

* Port 80 forwarded to Port 80 (HTTP)
* Port 443 forwarded to port 443 (HTTPS)

The load balancer health check should be configured as follows (the defaults are
fine for the values not listed):

* Ping Protocal: HTTPS
* Ping Port: 443
* Ping Path: ``/healthcheck.html``

Web Servers
-----------

Web servers are created automatically using FabulAWS.  The web servers run
Nginx, which proxies a lightweight Gunicorn-powered WSGI server for Django.
Also running on the webservers are PgBouncer and Stunnel, which proxy
connections to the database master and slave servers, both to speed up
connection times and to decrease the load of creating and destroying connections
on the actual database servers.

* Sample security groups: myproject-sg, myproject-web-sg

Worker Server
-------------

The worker server is very similar in configuration to the web servers, but it
runs on a small instance type and does not have Nginx installed.  Instead, it
is configured to run Celery, the Python package for periodic and background task
management.  This server is used for tasks like creating response file exports,
counting survey start and complete events as they happen, sending out scheduled
mailings, and other related tasks.  It exists as a separate server to isolate
the web servers (which are typically expected to respond very quickly to short
requests) from longer-running tasks.  Some background tasks may take 5-10
minutes or more to complete.

* Sample security groups: myproject-sg, myproject-worker-sg

Cache and Queue Server
----------------------

The cache and queue server runs Redis and RabbitMQ.  Redis is used both as a
cache and an HTTP session storage database.  RabbitMQ handles receiving tasks
from the web servers and delegating them to the worker server for completion.

* Sample security groups: myproject-sg, myproject-cache-sg, myproject-queue-sg

Database Master
---------------

The database master server runs PostgreSQL.  It allows encrypted connections
from the web and worker servers.

* Sample security groups: myproject-sg, myproject-db-sg

Database Slave
--------------

The database slave server also runs PostgreSQL, and is setup with streaming
replication from the master database server.  This results in very fast
(typically less than a few seconds) of lag time between the two machines.

* Sample security groups: myproject-sg, myproject-db-sg

Autoscaling
-----------

Each server environment uses EC2 Auto Scaling (AS) to bring up and down new
instances based on current demand.  When deploying, a new AS Launch
Configuration is created for the new revision of the code.  The AS Group, which
is created and managed largely via the EC2 console, is then updated via the API
to point to the new Launch Configuration.

SSL Certificates
----------------

SSL certifcates for the production and staging domains can be updated and
managed via the Elastic Load Balancers in the AWS console.  Internally, the
load balancer communicates with the web instances over SSL using the default
self-signed certificate that's created on a standard Ubuntu installation 
(``/etc/ssl/certs/ssl-cert-snakeoil.pem``).
