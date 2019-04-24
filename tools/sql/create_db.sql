CREATE DATABASE clinic_db ENCODING 'utf-8';
CREATE USER clinic_user WITH password 'UwrPr2cqRD4KKRMMNL43';
GRANT ALL privileges ON DATABASE clinic_db TO clinic_user;
ALTER DATABASE clinic_db OWNER TO clinic_user;
ALTER USER clinic_user WITH SUPERUSER;
