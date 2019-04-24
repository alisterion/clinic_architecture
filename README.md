Clinic App API
--------------

### Run project within docker machine

1. Install [docker-engine](https://docs.docker.com/engine/installation/)
2. Install [docker-compose](https://docs.docker.com/compose/install/)
3. Install [docker-machine](https://docs.docker.com/machine/install-machine/)
4. Install [virtualbox](https://www.virtualbox.org/wiki/Downloads)
5. Run command **docker-compose up --build**
    * server available at address: [127.0.0.1:10853](127.0.0.1:10853)
    * credentials superuser for access to admin page and api-docs:
        - username: test_user
        - email: test@test.com
        - password: testpass1234

For clear all docker images run command **sh docker-destroy-all.sh**


#### Run test within docker
    docker-compose run project python manage.py test --noinput


### Requirements for manual build project

1. Install dependencies
    * Apt requirements: 
        - python3.4 
        - python3-dev 
        - libjpeg-dev 
        - python-virtualenv 
        - postgresql-9.4 
        - postgresql-contrib-9.4 
        - postgresql-server-dev-9.X 
        - libproj-dev 
        - uwsgi 
        - uwsgi-plugin-python3
        - redis
        - rabbitmq-server
    * Install Postgis, see [here](https://docs.djangoproject.com/en/1.11/ref/contrib/gis/install/postgis/)
    * Install SpatiaLite, see [here](https://docs.djangoproject.com/en/1.11/ref/contrib/gis/install/spatialite/)

2. Create database
    * sudo -u postgres psql -f tools/sql/create_db.sql
    * sudo -u postgres psql -f tools/sql/create_test_db.sql
    * python manage.py migrate


> WARNING: DO NOT RUN TESTS ON PRODUCTION SERVER!
