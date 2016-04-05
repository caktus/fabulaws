Maintenance Tasks
=================

Describing an environment
-------------------------

While performing maintenance on an environment, it's sometimes helpful to know
exactly what servers are in that environment and what their load balancer
status is, if any.  To get a list of all servers in a given environment and
print some basic meta data about those servers, you can use the ``describe``
command to Fabric, like so::

    fab describe:myproject,<environment>

Adding new sysadmin users
-------------------------

If you don't have access to the servers yet, add your SSH public key in the
deployment/users/ directory.  To avoid having to pass a -u argument to fabric
on every deploy, make the name of the file identical to your local username.
Then ask someone who has access to run this command::

    fab staging update_sysadmin_users

Updating New Relic keys
-----------------------

To update the New Relic API and License keys, first find the new keys from
the new account. The License Key can be found from the main account page, and
the API key can be found via these instructions: https://docs.newrelic.com/docs/apis/api-key

Next, make sure your local fabsecrets_<environment>.py file is up to date::

    fab production update_local_fabsecrets

Next, update the ``newrelic_license_key`` and ``newrelic_api_key`` values
inside the ``fabsecrets_<environment>.py`` file with the new values. Then, update the keys
on the servers::

    fab staging update_server_passwords
    fab production update_server_passwords

Finally, update the configuration files containing the New Relic keys and
restart the Celery and Gunicorn processes::

    fab update_newrelic_keys:myproject,staging
    fab update_newrelic_keys:myproject,production

Note this short method of updating the configuration files involves a brief
moment of downtime (10-20 seconds). If no downtime is desired, you can
achieve the same result by repeating the following commands for each
environment, as needed (but it will take much longer, i.e., 30-60 minutes)::

    fab production upload_newrelic_sysmon_conf
    fab production upload_newrelic_conf
    fab deploy_serial:myproject,production

Copying the database from production to staging or testing
----------------------------------------------------------

To copy the production database on the staging server, run the following
command::

    fab staging reload_production_db

This will drop the current staging DB, create a new database, load it with a
copy of the current production data, and then run any migrations not yet run on
that database.  The same command will work on the testing environment by
replacing "staging" with "testing".  Internally, autoscaling is suspended and
an upgrade message is displayed on the servers while this command is in
progress.

Fixing an issue with broken site icons
--------------------------------------

If the button icons on the site appear as text rather than as images, there is
probably an issue with the CORS configuration for the underlying S3 bucket that
serves the font used to show these icons. To correct this, follow these steps:

First, navigate to the S3 bucket in the AWS Console, and click the Properties tab

Next, expand the Permissions section and then click Add CORS Configuration. The 
text in the popup should look something like this::

    <?xml version="1.0" encoding="UTF-8"?>
    <CORSConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <CORSRule>
            <AllowedOrigin>*</AllowedOrigin>
            <AllowedMethod>GET</AllowedMethod>
            <MaxAgeSeconds>3000</MaxAgeSeconds>
            <AllowedHeader>Authorization</AllowedHeader>
        </CORSRule>
    </CORSConfiguration>

Finally, click the Save button to add the configuration. **This step is important;
while it may appear that the configuration is already correct, it needs to
be saved before it will be added by S3.**

Stopping EC2 machines while not in use
--------------------------------------

Some types of instances, included db-master, db-slave, and worker servers,
can be stopped via the AWS console, later restarted, and then reconfigured
by running the following commands (in order)::

    fab <environment> mount_encrypted:roles=db-master
    fab <environment> mount_encrypted:roles=db-slave
    fab <environment> mount_encrypted:roles=worker

The cache server, due to an intricacy with how RabbitMQ stores its data
and configuration files, must be completely terminated and recreated (it does
not support changing the host's IP address). For more information, see:
http://serverfault.com/questions/337982/how-do-i-restart-rabbitmq-after-switching-machines

Web servers are managed via Amazon Auto Scaling. To terminate all web servers,
simply navigate to the AWS Auto Scaling Group and set the Minimum, Desired, and
Maximum number of instances to zero. Failure to complete this step may result
in the Auto Scaling Group perpetually attempting to bring up new web servers
and failing because no database servers exist.

Resizing servers or recreating an environment
---------------------------------------------

An entire environment can be recreated, optionally with different server sizes,
with a single command.  Note that this command takes a long time to run (30-60
minutes or even several hours, depending on the size of the database).  For this
reason, it is beneficial to clean out the database (see above) before downsizing
the servers because copying the database from server to server takes a
significant portion of this time.  That said, the environment will not be down
or inaccessible for this entire time; rather, the script does everything in an
order that minimizes the downtime required.  For a typical set of smaller
servers and an empty database, the downtime will usually be less than 2 minutes.

If you'd like to resize an environment, first edit the ``instance_types``
dictionary in ``fabulaws-config.yml`` to the sizes you'd like for the servers.
Here are the minimum sizes for each server type:

* cache: ``m1.small``
* db-master: ``m1.small``
* db-slave: ``m1.small``
* web: ``m1.small``
* worker: ``m1.medium``

Once the sizes have (optionally) been adjusted, you can recreate the environment
like so::

    fab recreate_servers:myproject,production

Updating Dependencies
---------------------

To circumvent the inevitable issues with PyPI during deployment, sdists for all
dependencies needed in the staging and production environments must be added to
the ``requirements/sdists/`` directory.  This means that, whenever you change in
``requirements/apps.txt``, you should make a corresponding change to the
``requirements/sdists/`` directory.

Adding or updating a single package
+++++++++++++++++++++++++++++++++++

To download a single sdist for a new or updated package, run the following
command, where ``package-name==0.0.0`` is a copy of the line that you added to
``requirements/apps.txt``::

    pip install package-name==0.0.0 -d requirements/sdists/

After downloading the new package, remove the outdated version from version
control, and add the new one along with the change to apps.txt.

Repopulating the entire sdists/ directory
+++++++++++++++++++++++++++++++++++++++++

You can also repopulate the entire sdists directory as follows::

    cd requirements/
    mkdir sdists_new/
    pip install -r apps.txt -d sdists_new/
    rm -rf sdists/
    mv sdists_new/ sdists/

Upgrading system packages
-------------------------

Since the site uses Amazon Auto Scaling, to ensure the servers have the latest
versions of Ubuntu packages we first need to update the web server image. This
can be done by running a new deployment, like so::

    fab deploy_serial:myproject,<environment>

Upgrading Ubuntu packages on the persistent (non-web) servers can be done with
the ``upgrade_packages`` Fabric command.  Before upgrading, it's best to take
the site offline and put it in upgrade mode to avoid any unexpected error pages
while services are restarted::

    fab <environment> begin_upgrade

Once the site is in upgrade mode, you can update packages on the servers as
follows::

    fab <environment> upgrade_packages

This command will connect to the servers one by one, run ``apt-get update``,
install any new packages needed by the web servers, and then run
``apt-get upgrade``.  You will be prompted to accept any upgrades that need to
take place, so you will have the opportunity to cancel the upgrade if needed
for any reason.

After verifying that the packages have installed successfully, you can bring the
site back online like so::

    fab <environment> end_upgrade
    
Note that upgrading may take some time, depending on the number of servers and
size of the upgrades, so it's best to schedule this during an off-hours
maintenance window.

