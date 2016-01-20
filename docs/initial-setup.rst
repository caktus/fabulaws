New Project Setup
=================

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

Local Machine
-------------

You'll need to make several changes to your local machine to use FabulAWS:

System Requirements
+++++++++++++++++++

* Ubuntu Linux 14.04 or later
* Python 2.7
* PostgreSQL 9.3
* virtualenv and virtualenvwrapper are highly recommended

AWS API Credentials
+++++++++++++++++++

First, you need to define the AWS credentials you created above in your shell
environment::

    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...

It's helpful to save these to a file (e.g., ``aws.sh``) that you can source
(``. aws.sh``) each time they're needed.

Passwords
---------

Local passwords
+++++++++++++++

A number of passwords are required during deployment.  To reduce the number of
prompts that need to be answered manually, you can use a file called
``fabsecrets.py`` in the top level of your repository.

If you already have a server environment setup, run the following command to
get a local copy of fabsecrets.py::

    fab <environment> update_local_fabsecrets 

**Note:** If applicable, this will not obtain a copy of  the ``luks_passphrase``
secret which for security's sake is not stored directly on the servers.  If you
will be creating new servers, this must be obtained securely from another
developer.

If this is a brand-new project, you can use the following template for
``fabsecrets.py``:

.. code-block:: python

  database_password = ''
  broker_password = ''
  smtp_password = ''
  newrelic_license_key = ''
  newrelic_api_key = ''
  s3_secret = ''

All of these are required to be filled in before any servers can be created.

Remote passwords
++++++++++++++++

To update passwords on the server, first retrieve a copy of ``fabsecrets.py``
using the above command (or from another developer) and then run the following
command::

    fab <environment> update_server_passwords

**Note:** It's only necessary to have a copy of ``fabsecrets.py`` locally if you
will be deploying new servers or updating the existing passwords on the
servers.

Project Configuration
---------------------

You'll need to add several files to your repository, typically at the top level.
You can use the following as templates:

fabfile.py
++++++++++

.. code-block:: python

  import logging

  root_logger = logging.getLogger()
  root_logger.addHandler(logging.StreamHandler())
  root_logger.setLevel(logging.WARNING)

  fabulaws_logger = logging.getLogger('fabulaws')
  fabulaws_logger.setLevel(logging.INFO)

  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)

  # XXX import actual commands needed
  from fabulaws.library.wsgiautoscale.api import *

fabulaws-config.yml
+++++++++++++++++++

.. code-block:: yaml

    instance_settings:
      # http://uec-images.ubuntu.com/releases/trusty/release/
      ami: ami-b2e3c6d8 # us-east-1 14.04.3 LTS 64-bit w/EBS-SSD root store
      key_prefix: 'myproject-'
      admin_groups: [admin, sudo]
      run_upgrade: true
      # Secure directories, volume, and filesystem info
      secure_root: #/secure # no trailing /
      secure_home: #/home/secure
      fs_type: ext4
      fs_encrypt: false
      ubuntu_mirror: us.archive.ubuntu.com
      # create swap of swap_multiplier * available RAM
      swap_multiplier: 1

  ## REMOTE SETTINGS ##
    deploy_user: myproject
    webserver_user: myproject-web
    database_host: localhost
    database_user: dbuser
    home: /home/myproject/
    python: /usr/bin/python2.7
    log_host: 

  ## LOCAL / PROJECT SETTINGS ##
    disable_known_hosts: true
    ssh_keys: deployment/users/
    password_names: [database_password, broker_password, smtp_password,
                     newrelic_license_key, newrelic_api_key, s3_secret]
    project: myproject
    wsgi_app: myproject.wsgi:application
    requirements_file: requirements/app.txt
    requirements_sdists:
    settings_managepy: myproject.local_settings
    static_html:
      upgrade_message: deployment/templates/html/503.html
      healthcheck_override: deployment/templates/html/healthcheck.html
    localsettings_template: deployment/templates/local_settings.py
    logstash_config: deployment/templates/logstash.conf
    backup_key_fingerprint: 
    vcs_cmd: git # or hg
    latest_changeset_cmd: git rev-parse HEAD # hg id -i # or git rev-parse HEAD
    repo: git@github.com:username/myproject.git
  # Mapping of Fabric deployments and environments to the Mercurial branch names
  # that should be deployed.
    branches:
      myproject:
        production: master
        staging: master
        testing: master

  ## SERVER SETTINGS ##

  # Local server port for pgbouner
    pgbouncer_port: 5432

  # Local server ports used by Gunicorn (the Django apps server)
    server_ports:
      staging: 8000
      production: 8001
      testing: 8002

  # Mapping of environment names to domain names. Used to update the
  # primary site in the database after a refresh and to set ALLOWED_HOSTS
  # Note that the first domain in the list must not be a wildcard as it
  # is used to update a Site object in the database.
  # Wildcard format used per ALLOWED_HOSTS setting
    site_domains_map:
      production:
      - dualstack.myproject-production-1-12345.us-east-1.elb.amazonaws.com
      staging:
      - dualstack.myproject-staging-1-12345.us-east-1.elb.amazonaws.com
      testing:
      - dualstack.myproject-testing-1-12345.us-east-1.elb.amazonaws.com

  ## ENVIRONMENT / ROLE SETTINGS ##

    default_deployment: myproject
    deployments:
    - myproject
    environments:
    - staging
    - production
    - testing
    valid_roles:
    - cache
    - db-master
    - db-slave
    - web
    - worker

  ## AWS SETTINGS ##

    region: us-east-1
    avail_zones:
    - e
    - c

  # Mapping of role to security group(s):
    security_groups:
      db-master: [myproject-sg, myproject-db-sg]
      db-slave: [myproject-sg, myproject-db-sg]
      cache: [myproject-sg, myproject-session-sg, myproject-cache-sg, myproject-queue-sg]
      worker: [myproject-sg, myproject-worker-sg]
      web: [myproject-sg, myproject-web-sg]

  # Mapping of environment and role to EC2 instance types (sizes)
    instance_types:
      production:
        cache: c3.large
        db-master: m3.xlarge
        db-slave: m3.xlarge
        web: c3.large
        worker: m3.large
      staging:
        cache: t1.micro
        db-master: m1.small
        db-slave: m1.small
        web: m1.small
        worker: m3.large
      testing:
        cache: t1.micro
        db-master: t1.micro
        db-slave: t1.micro
        web: m1.small
        worker: m1.small

  # Mapping of Fabric environment names to AWS load balancer names.  Load
  # balancers can be configured in the AWS Management Console.
    load_balancers:
      myproject:
        production:
        - myproject-production-1
        staging:
        - myproject-staging-1
        testing:
        - myproject-testing-1

  # Mapping of Fabric environment names to AWS auto scaling group names. Auto
  # scaling groups can be configured in the AWS Management Console.
    auto_scaling_groups:
      myproject:
        production: myproject-production-ag
        staging: myproject-staging-ag
        testing: myproject-testing-ag

  # Mapping of Fabric environment and role to Elastic Block Device sizes (in GB)
    volume_sizes:
      production:
        cache: 10
        db-master: 100
        db-slave: 100
        web: 10
        worker: 50
      staging:
        cache: 10
        db-master: 100
        db-slave: 100
        web: 10
        worker: 50
      testing:
        cache: 10
        db-master: 100
        db-slave: 100
        web: 10
        worker: 50

  # Mapping of Fabric environment and role to Elastic Block Device volume types
  # Use SSD-backed storage (gp2) for all servers. Change to 'standard' for slower
  # magnetic storage.
    volume_types:
      cache: gp2
      db-master: gp2
      db-slave: gp2
      web: gp2
      worker: gp2

    app_server_packages:
      - python2.7-dev
      - libpq-dev
      - libmemcached-dev
      - supervisor
      - mercurial
      - git
      - build-essential
      - stunnel4
      - pgbouncer

local_settings.py
+++++++++++++++++

This file should be placed at the location specified in ``fabulaws-config.yml``,
typically ``deployment/templates/local_settings.py``.

.. code-block:: python

  from myproject.settings import *

  DEBUG = False

  # logging settings
  #LOGGING['filters']['static_fields']['fields']['deployment'] = '{{ deployment_tag }}'
  #LOGGING['filters']['static_fields']['fields']['environment'] = '{{ environment }}'
  #LOGGING['filters']['static_fields']['fields']['role'] = '{{ current_role }}'
  AWS_STORAGE_BUCKET_NAME = '{{ staticfiles_s3_bucket }}'
  AWS_ACCESS_KEY_ID = 'YOUR-KEY-HERE'
  AWS_SECRET_ACCESS_KEY = "{{ s3_secret }}"

  # Tell django-storages that when coming up with the URL for an item in S3 storage, keep
  # it simple - just use this domain plus the path. (If this isn't set, things get complicated).
  # This controls how the `static` template tag from `staticfiles` gets expanded, if you're using it.
  # We also use it in the next setting.
  AWS_S3_CUSTOM_DOMAIN = '%s.s3.amazonaws.com' % AWS_STORAGE_BUCKET_NAME

  # This is used by the `static` template tag from `static`, if you're using that. Or if anything else
  # refers directly to STATIC_URL. So it's safest to always set it.
  STATIC_URL = "https://%s/" % AWS_S3_CUSTOM_DOMAIN

  # Tell the staticfiles app to use S3Boto storage when writing the collected static files (when
  # you run `collectstatic`).
  STATICFILES_STORAGE = 'storages.backends.s3boto.S3BotoStorage'

  # Auto-create the bucket if it doesn't exist
  AWS_AUTO_CREATE_BUCKET = True

  AWS_HEADERS = {  # see http://developer.yahoo.com/performance/rules.html#expires
      'Expires': 'Thu, 31 Dec 2099 20:00:00 GMT',
      'Cache-Control': 'max-age=94608000',
  }

  # Having AWS_PRELOAD_META turned on breaks django-storages/s3 -
  # saving a new file doesn't update the metadata and exists() returns False
  #AWS_PRELOAD_METADATA = True

  # database settings
  DATABASES = {
  {% for server in all_databases %}
      '{{ server.database_key }}': {
          'ENGINE': 'django.db.backends.postgresql_psycopg2',
          'NAME': '{{ server.database_local_name }}',
          'USER': '{{ database_user }}',
          'PASSWORD': '{{ database_password }}',
          'HOST': 'localhost',
          'PORT': '{{ pgbouncer_port }}',
      },{% endfor %}
  }

  # django-balancer settings
  DATABASE_POOL = {
  {% for server in slave_databases %}
      '{{ server.database_key }}': 1,{% endfor %}
  }
  MASTER_DATABASE = '{{ master_database.database_key }}'

  # media roots
  MEDIA_ROOT = "{{ media_root }}"
  STATIC_ROOT = "{{ static_root }}"

  # email settings
  EMAIL_HOST_PASSWORD = '{{ smtp_password }}'
  EMAIL_SUBJECT_PREFIX = '[{{ deployment_tag }} {{ environment }}] '

  # Redis DB map:
  # 0 = cache
  # 1 = unused (formerly celery task queue)
  # 2 = celery results
  # 3 = session store
  # 4-16 = (free)

  # Cache settings
  CACHES = {
      'default': {
          'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
          'LOCATION': '{{ cache_server.internal_ip }}:11211',
          'VERSION': '{{ current_changeset }}',
      },
      'session': {
          'BACKEND': 'redis_cache.RedisCache',
          'LOCATION': '{{ cache_server.internal_ip }}:6379',
          'OPTIONS': {
              'DB': 3,
          },
      },
  }

  # Task queue settings

  # see https://github.com/ask/celery/issues/436
  BROKER_URL = "amqp://{{ deploy_user }}:{{ broker_password }}@{{ cache_server.internal_ip }}:5672/{{ vhost }}"
  BROKER_CONNECTION_TIMEOUT = 4
  BROKER_POOL_LIMIT = 10
  CELERY_RESULT_BACKEND = "redis://{{ cache_server.internal_ip }}:6379/2"

  # Session settings
  SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
  SESSION_CACHE_ALIAS = 'session'

  # django-compressor settings
  COMPRESS_URL = STATIC_URL
  # Use MEDIA_ROOT rather than STATIC_ROOT because it already exists and is
  # writable on the server.
  COMPRESS_ROOT = MEDIA_ROOT
  COMPRESS_STORAGE = STATICFILES_STORAGE
  COMPRESS_OFFLINE = True
  COMPRESS_OFFLINE_MANIFEST = 'manifest-{{ current_changeset }}.json'
  COMPRESS_ENABLED = True

  ALLOWED_HOSTS = [{% for host in allowed_hosts %}'{{ host }}', {% endfor %}]

SSH keys
++++++++

Before attempting to deploy for the first time, you should add your SSH public key
to a file named ``deployment/users/<yourusername>`` in the repository. This path
can also be configured in ``fabulaws-config.yml``. Multiple SSH keys are permitted
per file, and additional files can be added for each username (developer).

Django Settings
+++++++++++++++

FabulAWS uses django_compressor and django-storages to store media on S3. The following
settings changes are required in your base ``settings.py``:

#. 'compressor' and 'storages' should be added to your ``INSTALLED_APPS``.
#. Add the following to the end of your ``settings.py``, modifying as needed:

  .. code-block:: python

    # List of finder classes that know how to find static files in
    # various locations.
    STATICFILES_FINDERS = (
        'django.contrib.staticfiles.finders.FileSystemFinder',
        'django.contrib.staticfiles.finders.AppDirectoriesFinder',
        'compressor.finders.CompressorFinder',
    )

    STATIC_ROOT = os.path.join(BASE_DIR, 'static')

    COMPRESS_ENABLED = False # enable in local_settings.py if needed
    COMPRESS_CSS_HASHING_METHOD = 'hash'
    COMPRESS_PRECOMPILERS = (
        ('text/less', 'lessc {infile} {outfile}'),
    )

wsgi.py
+++++++

You'll need to change the default ``DJANGO_SETTINGS_MODULE`` in your project's
``wsgi.py`` to ``myproject.local_settings``.

Python Requirements
+++++++++++++++++++

The following are the minimum Python requirements for deploying a web application
using FabulAWS:

.. code-block:: text

  Django==1.8.8
  psycopg2==2.6.1
  pytz==2015.2
  django-celery==3.1.16
  Celery==3.1.18
  kombu==3.0.26
  amqp==1.4.6
  gunicorn==0.17.4
  django-balancer==0.4
  boto==2.39.0
  django-storages==1.1.8
  django_compressor==1.5
  python-memcached==1.52
  redis==2.10.3
  django-redis-cache==1.3.0
  django-cache-machine==0.9.1
  newrelic==2.44.0.36

In addition, the following requirements are needed for deployment:


.. code-block:: text

  pyyaml==3.11
  fabric==1.10.2
  argyle==0.2.1
