Useful commands
===============

Mega-commands
-------------

* ``fab describe:deployment,environment`` - Show the config and existing servers
* ``fab create_environment:deployment,environment`` - create all the initial servers. After this, you might need to bump up the instances in the autoscaling group to get web servers going.
* ``fab update_environment:deployment,environment`` - run update_sysadmin_users, update_server_passwords, and upgrade_packages
* ``fab environment update_services`` - does upload_newrelic_conf,
  upload_supervisor_conf, upload_pgbouncer_conf, and upload_nginx_conf

Deploys
-------

All-in-one commands:

* ``fab deploy_serial:deployment,environment[,launch_config_name]`` - Create a new launch config
  if a name is not provided. Update the ASG to use the provided or new launch config. Take
  web servers down one at a time and bring up new ones, so you end up with all new ones without
  downtime.
* ``fab deploy_full:deployment,environment[,launch_config_name]`` - Create a new launch config
  if a name is not provided. Update the ASG to use the provided or new launch config. Take
  all the web servers down and bring up new ones. This is faster than deploy_serial but
  does cause downtime.

More low-level commands:

* ``fab create_launch_config_for_deployment:deployment,environment`` - Create a new launch
  config and print its name, but do not use it for anything. Typically you could use this
  and then follow with one of the deploy commands, providing the launch_config_name that
  was output from this command.
* ``fab environment begin_upgrade`` - puts up a maintenance page for all requests (the deploy_xxx commands do this for you)
* ``fab environment deploy_web[:changeset]`` - deploy to web servers (update them in place, do not update LC or ASG), restart processes
* ``fab environment deploy_worker[:changeset]`` - deploy to worker (update in place), restart processes
* ``fab environment flag_deployment`` - sends a message to New Relic that the
  current code revision has just been deployed
* ``fab environment end_upgrade`` - reverses begin_upgrade

Misc
----

* ``fab environment update_sysadmin_users`` - create or update dev users on servers
* ``fab environment upgrade_packages`` - upgrade all Ubuntu packages on servers
* ``fab environment mount_encrypted`` - see source

EC2 instances
-------------

* ``fab new:deployment,environment,role[,avail_zone[,count]]``

Handling secrets
----------------

* ``fab environment update_local_fabsecrets``
* ``fab environment update_server_passwords`` - push secrets from local file to servers (except luks_passphrase)

Supervisor
----------

* ``fab environment upload_supervisor_conf``
* ``fab environment supervisor:command,group[,process]`` - runs 'supervisorctl command environment-group:environment-process', or 'supervisorctl command environment-group'

Examples:

* fab testing supervisor:stop,web
* fab testing supervisor:stop,celery
* fab testing supervisor:stop,pgbouncer
* fab testing supervisor:start,pgbouncer etc.

Python/Django
-------------

web servers & worker:

* ``fab environment update_requirements`` - does a pip install (without -U) (on all webs & worker)
* ``fab environment update_local_settings`` - render local settings template
  and install it on the servers (but does not restart services) (on all webs & worker)
* ``fab environment bootstrap`` - clones source repo, updates services,
  creates an virtual env and installs Python packages (on all webs & worker)
* ``fab environment clone_repo`` -- clones the source repo (on all webs & worker)
* ``fab environment update_source`` - updates checked-out source (on all webs & worker)
* ``fab environment current_changeset`` - check latest code from repo (on all webs & worker)

worker only:

* ``fab environment managepy:command`` - run a manage.py command on worker
* ``fab environment migrate`` - run a migrate command on worker
* ``fab environment collectstatic`` - run a migrate command on worker
* ``fab environment dbbackup`` - run a database backup using dbbackup
* ``fab environment dbrestore`` - run a database restore - see code for now for more info

Databases
---------

* ``fab environment upload_pgbouncer_conf``
* ``fab reload_production_db[:prod_env[,src_env]]``
* ``fab reset_local_db:dbname``
* ``fab environment reset_slaves`` - this resets the config & data on the db slaves and is a good
  way to get things back into a working state if the replication seems broken
* ``fab environment promote_slave[:index]`` - change slave `index` to be the master. After this, run update_local_settings to make the web servers use the new settings.


Nginx
-----

* ``fab environment upload_nginx_conf``
* ``fab environment restart_nginx``

Newrelic
--------

* ``fab environment upload_newrelic_conf``
* ``fab update_newrelic_keys:deployment,environment`` - especially useful because it
  restarts the Django processes, even if you don't need to change the
  New Relic config.
