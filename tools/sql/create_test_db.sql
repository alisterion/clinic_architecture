CREATE DATABASE test_clinic_db ENCODING 'utf-8';
CREATE USER test_clinic_user WITH password '9zW3qKwU6w';
GRANT ALL privileges ON DATABASE test_clinic_db TO test_clinic_user;
ALTER DATABASE test_clinic_db OWNER TO test_clinic_user;
ALTER USER test_clinic_user CREATEDB;
ALTER USER test_clinic_user WITH SUPERUSER;
