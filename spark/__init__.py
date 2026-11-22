"""PySpark + Delta Lake track: rebuilds the warehouse's three fact tables in a medallion
layout (bronze -> silver -> gold) and proves they equal the T-SQL results.

In a notebook, import the modules (`from spark import run as lakehouse`) rather than
`import spark`: notebooks already use the name `spark` for the SparkSession.
"""
