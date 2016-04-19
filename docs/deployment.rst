Deployment
==========

FabulAWS uses `Fabric <http://docs.fabfile.org/>`_ for deployment, with which
some familiarity is strongly recommended.  This page assumes that you've
completed the necessary setup described in the :doc:`/architecture`.
You will also need a local development environment setup as described in
:doc:`/initial-setup`.

.. IMPORTANT::
   When deploying to an environment, your local copy of the code
   should be up to date and must also have a checkout of the correct branch.
   Environments can be mapped to branches in the ``fabulaws-config.yml`` file.

Testing environment
-------------------

The **testing environment** is usually a temporary environment that can be used
for load testing, deployment testing, or other activities that would otherwise
negatively impact the primary environment for testing new features (see
:ref:`staging-environment` below).

To create a new instance of the testing environment, you can use the
``create_environment`` command to Fabric, like so::

    fab create_environment:myproject,testing

Prior to running this command, be certain that all prior instances of testing
servers have been terminated via the AWS console.  This command will create
all the required servers in parallel.  To avoid difficulty with determining
which server failed to be created when a problem is encountered, the logs for
server creation are saved to separate files.  *Always check these files to
ensure that the servers were created successfully.*


.. _staging-environment:

Staging environment
-------------------

The **staging environment** is typically used for testing and quality assurance
of new features. It also serves as a testing ground for doing the deployment
itself. New features (even small bug fixes) should be deployed to and tested on
the staging environment prior to being deployed to the production environment.

The staging environment is usually a copy of the production environment running
on smaller (cheaper) virtual machines at EC2.  It also typically contains a
recent snapshot of the production database, so any issues specific to the
production environment can be tested on staging without affecting usability of
the production site.

.. _production-environment:

Production environment
----------------------

The **production environment** is typically hosts the live servers in use by the
the application's end-users.

Deployment methods
------------------

Since FabulAWS uses Amazon Autoscaling, special care must be taken to update
the autoscaling image at the same time as new code is deployed.

Autoscaling: Updating the image
+++++++++++++++++++++++++++++++

Because AMI creation can be a time-intensive part of the process, it can be
done separately ahead of time to prepare for a deployment.

To create an autoscaling AMI and launch configuration based on the current
version of the code (from the appropriate branch - see above), run the
following command::

    fab create_launch_config_for_deployment:myproject,<environment>

This command will print out the name of the created launch configuration, which
can be passed into the associated autoscaling deployment methods below. If
needed, the launch configuration names and associated images can also be found
via the AWS console.

Autoscaling: Full deployment
++++++++++++++++++++++++++++

A "full" deployment should be used any time there are backwards-incompatible
updates to the application, i.e., when having two versions of the code running
simultaneously on different servers might have damaging results or raise errors
for users of the site.  Note that this type of deployment requires downtime,
which may need to be scheduled ahead of time depending on which environment is
impacted.

With autoscaling, a full deployment works as follows:

#. First, the autoscaling group's ability to add new instances to the load
   balancer is suspended, a new launch configuration for the new version of the
   code is installed, and the desired number of instances for the group is
   doubled.  This has the effect of spinning up all the new required instances
   without adding them to the load balancer.
#. Once those instances have been created, the "upgrade in progress" message
   is displayed on *all* the servers, ``deploy_worker`` is run to update the
   database schema and any static media, and the autoscaling group's ability to
   add instances to the load balancer is resumed. The process then waits for all
   instances to be healthy in the load balancer.
#. Finally, the old instances in the group are terminated, and the "upgrade in
   progress" message is removed from the new servers.

The syntax for completing a full deployment is as follows::

    fab deploy_full:myproject,<environment>[,<launch config name>]

The launch configuration name is optional, and one will be created automatically
if not specified.

.. NOTE::
   This command does not update secrets from your local file to the servers. If you want to do that,
   explicitly run ``fab <environment> update_server_passwords`` before running this command.

Autoscaling: Serial deployment
++++++++++++++++++++++++++++++

A "serial" deployment can be used any time the changes being deployed are minimal
enough that having both versions of the code running simultaneously will not
cause problems. This is usually the case any time there are minor, code-only
(non-schema) updates. Each server points to a separate copy of the static media
specific to the version of the code that it's running, so backwards incompatible
CSS and JavaScript changes can safely be deployed serially.

Serial deployments with autoscaling work by gradually marking instances in the
autoscaling group as unhealthy, and then waiting for the group to create a new,
healthy instance before proceeding. A serial deployment can be started as
follows::

    fab deploy_serial:cmyproject,<environment>[,<launch config name>]

Again, the launch config is optional and one will be created automatically if
not specified.

.. NOTE::
   This command does not update secrets from your local file to the servers. If you want to do that,
   explicitly run ``fab <environment> update_server_passwords`` before running this command.

.. NOTE::
   You may see errors that look like this while running a serial deployment::

    400 Bad Request
    <ErrorResponse xmlns="http://elasticloadbalancing.amazonaws.com/doc/2012-06-01/">
      <Error>
        <Type>Sender</Type>
        <Code>InvalidInstance</Code>
        <Message>Could not find EC2 instance i-1bb70c35.</Message>
      </Error>
      <RequestId>9b3dc6a5-850e-11e3-9e35-b9e8294315ba</RequestId>
    </ErrorResponse>

These errors are expected and simply mean that the elastic load balancer is not
yet aware of the newly created instance.

Suspending and restarting autoscaling processes
+++++++++++++++++++++++++++++++++++++++++++++++

If for any reason autoscaling needs to be suspended, this can be accomplished
through Fabric.  To suspend all autoscaling processes, simply run::

    fab suspend_autoscaling_processes:myproject,<environment>

To resume autoscaling once any issues have been resolved, run::

    fab resume_autoscaling_processes:myproject,<environment>

A note about usernames
----------------------

If you get a prompt that looks something like this when you attempt to deploy,
it's quite possible that you're giving the remote server the wrong username (or
you don't have access to the servers to begin with)::

    [ec2-23-22-145-188.compute-1.amazonaws.com] Passphrase for private key:

When deploying to any environment, if your local username is different from the
username you use to login to the remote server, you need to give Fabric a
username on the command line, like so::

    fab -u <remoteusername> <environment> <commands>
