.. FabulAWS documentation master file, created by
   sphinx-quickstart on Wed Sep  7 09:15:33 2011.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

FabulAWS
========

`FabulAWS <https://github.com/caktus/fabulaws>`_ is a tool for deploying Python
web applications to autoscaling-enabled AWS EC2 environments.

Simple example
--------------
FabulAWS lets you create EC2 instances using a context manager in Python and
easily execute work on that instance. Typical workflow might look like this::

    from fabulaws.ec2 import MicroLucidInstance
    
    with MicroLucidInstance():
        run('uname -a')

If needed, you can extend the instance classes defined in the ``fabulaws.ec2``
module as needed to further customize the instance before presenting it as
a context manager (or using it in your fab file).  To do so, simply extend
the ``setup()`` and ``cleanup()`` methods in one of the existing classes.

Contents
--------

.. toctree::
   :maxdepth: 2

   architecture
   initial-setup
   deployment
   maintenance
   troubleshooting
   internals
   useful_commands

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

