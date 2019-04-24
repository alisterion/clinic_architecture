FROM odoku/geopython:3.4

# apt-requirements
RUN apk update --no-cache && apk add --no-cache gcc \
    && ln -sf /usr/bin/gcc /usr/bin/cc1 \
    && apk add --no-cache \
        build-base python3-dev libjpeg zlib zlib-dev jpeg-dev\
        postgresql-dev libffi-dev linux-headers binutils libstdc++\
    && pip3 install -U pip setuptools \
    && pip3 install uwsgi

ADD ["requirements.txt", "tools/docker-utils/entrypoint.sh", "/srv/www/ClinicApp/"]

# requirements
RUN pip3 install -r /srv/www/ClinicApp/requirements.txt \
    && apk del gcc build-base linux-headers && rm -rf /var/cache/apk/* \
    && cp /srv/www/ClinicApp/entrypoint.sh /entrypoint.sh \
    && chmod +x /entrypoint.sh
