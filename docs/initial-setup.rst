New Project Setup
=================

AWS Configuration
-----------------

Some configuration within the AWS console is necessary to begin using FabulAWS:

IAM User
++++++++

First, you'll need to create credentials via IAM that have permissions to create
servers in EC2 and manage autoscaling groups and load balancers. Amazon will provide you with a
credentials file which will contain ``AWS_ACCESS_KEY_ID`` and ``AWS_SECRET_ACCESS_KEY``, which you
will need later in this document.


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
   * For EC2-classic:
      * TCP port 80 from amazon-elb/amazon-elb-sg
      * TCP port 443 from amazon-elb/amazon-elb-sg
   * For VPC-based AWS accounts:
      * TCP port 80 from myproject-web-sg
      * TCP port 443 from myproject-web-sg
* **myproject-worker-sg**
   * (used only as a source - requires no additional firewall rules)
* **myproject-incoming-web-sg**
   * TCP port 80 from any address
   * TCP port 443 from any address

Load Balancer
+++++++++++++

You will need to create a load balancer for your instances, at least one for
each environment. Note that multiple load balancers can be used if the site
serves different domains (though a single load balancer can be used for a
wildcard SSL certificate). Use the following parameters as a guide:

* Choose a name and set it in ``fabulaws-config.yml``
* Ports 80 and 443 should be mapped to 80 and 443 on the instances
* If on EC2-Classic (older AWS accounts), you can use 'EC2-Classic' load balancers.
  Note that this will cause a warning to be shown when you try to 'Assign Security Groups'.
  That warning can be skipped.
* If on newer, VPC-based AWS accounts:

  * Add security group **myproject-incoming-web-sg** to the load balancer so
    the load balancer can receive incoming requests.
  * Add security group **myproject-web-sg** to the load balancer so the backend instances will
    accept forwarded requests from the load balancer.
* Setup an HTTPS health check on port 443 that monitors ``/healthcheck.html``
  at your desired frequency (you'll setup the health check URL in your app below)
* Backend authentication and stickiness should be disabled
* The zones chosen should match those in ``fabulaws-config.yml`` (typically 2)
* Configure a custom SSL certificate, if desired.

After the load balancer is created, you can set the domain name for the
associated environment ``fabulaws-config.yml`` to your custom domain or the
default domain for the load balancer.

Auto Scaling Group
++++++++++++++++++

You will also need to create one auto scaling group per envrionment, with the
following parameters:

* Choose a name and set it in ``fabulaws-config.yml``
* Choose an existing dummy launch config and set it with a "min" and "desired" instances
  of 0 to start, and a "max" of at least 4 (a higher max is fine).
* Select Advanced, choose your load balancer, and select the ELB health check
* Choose the same availability zones as for your load balancer
* You don't need to configure scaling policies yet, but these will need to be
  set eventually based on experience
* You must configure the auto scaling group to tag instances like so:
   * **Name:** myproject_<environment>_web
   * **deployment:** myproject
   * **environment:** <environment>
   * **role:** web

Local Machine
-------------

You'll need to make several changes to your local machine to use FabulAWS:

System Requirements
+++++++++++++++++++

* Ubuntu Linux 18.04 or later
* Python 3.8
* PostgreSQL 10
* virtualenv and virtualenvwrapper are highly recommended

AWS API Credentials
+++++++++++++++++++

First, you need to define the AWS credentials you created above in your shell
environment:

.. code-block:: sh

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
``fabsecrets_<environment>.py`` in the top level of your repository.

If you already have a server environment setup, run the following command to
get a local copy of fabsecrets_<environment>.py::

    fab <environment> update_local_fabsecrets

**Note:** If applicable, this will not obtain a copy of  the ``luks_passphrase``
secret which for security's sake is not stored directly on the servers.  If you
will be creating new servers, this must be obtained securely from another
developer.

If this is a brand-new project, you can use the following template for
``fabsecrets_<environment>.py``:

.. literalinclude:: sample_files/fabsecrets.py
   :language: python

All of these are required to be filled in before any servers can be created.

Remote passwords
++++++++++++++++

To update passwords on the server, first retrieve a copy of ``fabsecrets_<environment>.py``
using the above command (or from another developer) and then run the following
command::

    fab <environment> update_server_passwords

.. NOTE::
   It's only necessary to have a copy of ``fabsecrets_<environment>.py`` locally if you
   will be deploying new servers or updating the existing passwords on the servers.

.. NOTE::
   This command is really only useful on the web and worker servers. On all other servers,
   nothing will update the configuration files to use the new secrets.

Project Configuration
---------------------

You'll need to add several files to your repository, typically at the top level.
You can use the following as templates:

fabfile.py
++++++++++

.. literalinclude:: sample_files/fabfile.py
   :language: python

fabulaws-config.yml
+++++++++++++++++++

.. literalinclude:: sample_files/fabulaws-config.yaml
   :language: yaml

local_settings.py
+++++++++++++++++

This file should be placed at the location specified in ``fabulaws-config.yml``,
typically ``deployment/templates/local_settings.py``.

.. literalinclude:: sample_files/local_settings.py
   :language: python

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

#. ``compressor``, ``storages``, and ``djcelery`` should be added to your
   ``INSTALLED_APPS``.
#. Add the following to the end of your ``settings.py``, modifying as needed:

.. code-block:: python

  # Celery settings
  import djcelery
  from celery.schedules import crontab
  djcelery.setup_loader()

  CELERY_SEND_TASK_ERROR_EMAILS = True

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

Static HTML
+++++++++++

You need to create two static HTML files, one for displaying an upgrade message
while you're deploying to your site, and one to serve as a "dummy" health check
to keep instances in your load balancer healthy while deploying.

The paths to these files can be configured in the ``static_html`` dictionary
in your ``fabulaws-config.yml``:

.. code-block:: yaml

  static_html:
    upgrade_message: deployment/templates/html/503.html
    healthcheck_override: deployment/templates/html/healthcheck.html

The ``503.html`` file can contain anything you'd like. We recommend something
distictive so that you can tell if your health check is being served by Django
or the "dummy" health check html file, e.g.: ``OK (nginx override)``

Similarly, the ``healthcheck.html`` can contain anything you'd like, either
something as simple as ``Upgrade in progress. Please check back later.`` or
a complete HTML file complete with stylesheets and images to display a "pretty"
upgrade-in-progress message.

Basic Auth
++++++++++

If you want to add HTTP Basic Auth to a site, add a section to ``fabulaws-config.yml``
like this:

.. code-block:: yaml

  # Any sites that need basic auth
  # This is NOT intended to provide very high security.
  use_basic_auth:
    testing: True
    anotherenv: True

Add ``basic_auth_username`` and ``basic_auth_password`` to ``password_names``:

.. code-block:: yaml

  password_names: [a, b, c, ..., basic_auth_username, basic_auth_password]

And add the desired username and password to each environment secrets file:

.. code-block:: yaml

  basic_auth_username: user1
  basic_auth_password: password1

You'll need to add these entries to all secrets files; just set them to an
empty string for environments where you are not using basic auth.

Then in the ``testing`` and ``anotherenv`` environments, fabulaws will apply
basic auth to the sites. For testing, user ``user1`` will be able to use password
``password1``, and so forth.

.. NOTE::
   Fabulaws will also turn off Basic Auth for the health check URL so that the load balancer
   can access it. It assumes that the health check URL is ``/healthcheck.html`` and that Django will
   be serving the health check URL (rather than being served as a static file directly by Nginx, for
   example). If either of those assumptions are not correct, you will need to tweak it by copying
   and modifying the template for nginx.conf.

Health Check
++++++++++++

You'll need to configure a health check within Django as well. Following is
a sample you can use.

Add to ``views.py``:

.. code-block:: python

  import logging

  from django.db import connections
  from django.http import HttpResponse, HttpResponseServerError


  def health_check(request):
      """
      Health check for the load balancer.
      """
      logger = logging.getLogger('fabutest.views.health_check')
      db_errors = []
      for conn_name in connections:
          conn = connections[conn_name]
          try:
              cursor = conn.cursor()
              cursor.execute('SELECT 1')
              row = cursor.fetchone()
              assert row[0] == 1
          except Exception, e:
              # note that there doesn't seem to be a way to pass a timeout to
              # psycopg2 through Django, so this will likely not raise a timeout
              # exception
              logger.warning('Caught error checking database connection "{0}"'
                             ''.format(conn_name), exc_info=True)
              db_errors.append(e)
      if not db_errors:
          return HttpResponse('OK')
      else:
          return HttpResponseServerError('Configuration Error')

Add lines similar to those highlighted below to your ``urls.py``:

.. code-block:: python

  from django.conf.urls import include, url
  from django.contrib import admin

  from fabutest import views as fabutest_views

  urlpatterns = [
      url(r'^admin/', include(admin.site.urls)),
      url(r'^healthcheck.html$', fabutest_views.health_check),
  ]

Python Requirements
+++++++++++++++++++

The following are the minimum Python requirements for deploying a web application
using FabulAWS (update version numbers as needed).  (Other versions might work,
but these are the ones that Fabulaws has most recently been confirmed to work with.)

.. code-block:: text

  Django==2.2.13
  psycopg2==2.8.5
  pytz==2020.1
  celery==4.4.3
  gunicorn==20.0.4
  django-balancer==0.5
  boto3==1.13.19
  django-storages==1.9.1
  django-compressor==2.4
  python-memcached==1.59
  redis==3.5.2
  django-redis-cache==2.1.1
  django-cache-machine==1.1.0
  newrelic==5.12.1.141
  Fabric3

First Deployment
----------------

Once you have your EC2 environment and project configured, it's time to create
your initial server environment.

To create a new instance of the testing environment, you can use the
``create_environment`` command to Fabric, like so::

    fab create_environment:myproject,testing

In addition to the console, be sure to inspect the log files generated (``*.out``
in the current directory) to troubleshoot any problems that may arise.

For more information, please refer to the :doc:`/deployment` documentation.
