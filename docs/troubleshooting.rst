Troubleshooting server issues
=============================

Managing SSH host keys
----------------------

Amazon will regularly reuse IP addresses for servers, which can cause conflicts
with your local ssh host keys (``~/.ssh/known_hosts`` on most systems).  If you
see a message like this while creating a server, you'll know you're affected by
this::

    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    @    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
    Someone could be eavesdropping on you right now (man-in-the-middle attack)!
    It is also possible that a host key has just been changed.

If you see this message, you will need to terminate the server being created,
delete the host key (for both the hostname and the IP address) from your
``known_hosts`` file, and re-create the server.

Resetting a troubled environment
--------------------------------

If all the servers and services in an environment appear to be running
properly but the web frontend or worker still isn't functioning, one of the
quickest ways to "reset" an environment is to run a deployment.  Before
attempting more extreme measures, you can run a deployment to get all
the config files in sync and restart many of the services that make up
the application, like so::

    fab <environment> begin_upgrade deploy_worker deploy_web end_upgrade

Fixing Celery when it won't stop
--------------------------------

Celery occassionally gets into a state when it won't stop and may be pegging
the CPU.  If this happens (e.g., if the ``deploy_worker`` command hangs
indefinitely while stopping the Celery workers), you may need to SSH to the
worker server manually and run::

    sudo killall -9 celery

If this doesn't work, you can revert to manually finding the PIDs of the stuck
Celery processes in ``ps auxww`` or ``top`` and killing them with::

    sudo kill -9 <PID>

After doing this, be sure to run ``deploy_worker`` (or if it was already
running, let it complete) so as to restore Celery to a running state again.

Master database goes down
-------------------------

If the master database goes down, manually make sure it's permanently lost
before converting a slave into the master.  At this point you probably also
want to enable the pretty upgrade message on all the web servers::

   fab <environment> begin_upgrade

Any slave can be "promoted" to the master role via fabric, as follows::

    fab <environment> promote_slave

This will tag the old master as "decommissioned" in AWS, tag the slave as
the new master, and then run the Postgres command to promote a slave to the
master role.

After promoting a slave, you need to reconfigure all the web servers to use
the new master database.  The easiest way to do that is through a deployment::

    fab <environment> deploy_worker deploy_web

If you had more than one slave database before promoting a slave, the additional
slaves need to be reset to stream from the new master.  This can be accomplished
with the ``reset_slaves`` command::

    fab <environment> reset_slaves

Once complete, you can disable the upgrade message and resume usage of the
site::

    fab <environment> end_upgrade

Slave database goes down
-------------------------

If a slave database goes down, first enable the pretty upgrade message on all
the web servers::

   fab <environment> begin_upgrade

The site can operate in a degraded state with only a master database.  To do
that, navigate to the AWS console and stop or re-tag the old slave server so
it can no longer be discovered by Fabric.  Then, run a deployment to update
the local settings files on all the web servers::

    fab <environment> deploy_worker deploy_web

Once complete, you can disable the upgrade message and resume usage of the
site::

    fab <environment> end_upgrade

Adding a new slave
------------------

If a slave database is lost (either due to promotion to the master role or
because it was itself lost), it is desirable to return the application to
having two or more database servers as soon as possible.  To add a new slave
database to the Postgres cluster, first create a new server
as follows::

    fab new:myproject,<environment>,db-slave,X

where X is the availability zone in which you wish to create the server (it
should be created in a zone that doesn't already have a database server, or
has the fewest database servers).

Next, configure the web servers to begin using the new slave by doing a serial
deployment::

    fab deploy_serial:myproject,<environment>

This will take the web servers down one at a time, deploy the latest code,
and update the settings file to use the newly added database server.

Slave database loses replication connection
-------------------------------------------

While PostgreSQL administration is outside the scope of this guide, if you
have determined that a slave database has lost the replication connection
to the master database and you prefer not to simply create a new slave
database server, you can re-sync the slave(s) with the master with the
following command::

    fab <environment> reset_slaves

Web server dies
---------------

Web servers are disposable, and are automatically recreated by via autoscaling
if they become unhealthy.

Worker server dies
------------------

Worker servers are also disposable, so the easiest way to recover from one
dying is simply to destroy it and create another.  To destroy the instance,
make sure that it's really dead (try SSHing to it and/or rebooting it from the
AWS console).  If all else fails, you can terminate the instance from the
console (unless you want to leave it around to troubleshoot what went wrong).

Adding a new worker server
--------------------------

Creating a new worker server works the same as creating a web server::

    fab new:myproject,<environment>,worker,X

where X is the availability zone in which you wish to create the server.

After creating the worker, you will also need to update it with correct
settings file and start the worker processes.  This can be done by running::

    fab <environment> deploy_worker

Cache service goes down
-----------------------

If one of the services (e.g., RabbitMQ or Redis) simply dies on the cache
server, SSH to that machine and attempt to start it by hand.  RabbitMQ has been
known on at least one occasion to have shutdown by itself for no apparent
reason.

Cache server (RabbitMQ and Redis) fails
---------------------------------------

If the cache server fails, the web site will be inaccessible until a new server
is created because the site relies on using Redis as a session store.  As such,
first display the pretty upgrade message on the servers::

    fab <environment> begin_upgrade

Now, create a new cache server as follows::

    fab new:myproject,<environment>,cache,X

where X is the availability zone in which you wish to create the server.
Typically this should be one of the two zones that the web servers reside in.

While the new server is being created, navigate to the AWS console and stop
or re-tag the old cache server so it can no longer be discovered by Fabric.

Once the new server has finished building, update the configuration on all the
servers by running a deployment::

    fab <environment> deploy_worker deploy_web

When that's complete, disable the upgrade message on the web servers::

   fab <environment> end_upgrade

Web servers churning during a deploy
------------------------------------

If you see web servers being launched, but then being terminated before they come into service, this
is usually due to a problem with the load balancer not receiving a healthy response from the health
check. If the web server is returning a 500 error, you should hopefully get an error email, which
will help you debug the problem. If you get a 4xx error, you may not, so you might not even be aware
that the web servers are churning. Once you are aware, suspend autoscaling::

  fab suspend_autoscaling_processes:myproject,<environment>

SSH into the web server in question. Look at the
``/home/myproject/www/{environment}/log/access.log`` and see what HTTP status code is being returned
to the load balancer.

* 401 errors mean the load balancer is getting a Basic Auth check which it is failing.
* 404 errors mean the health check URL is incorrectly configured, either due to a misconfiguration
  in Nginx or in Django.

Remember to resume autoscaling once you have fixed the problem::

  fab resume_autoscaling_processes:myproject,<environment>
