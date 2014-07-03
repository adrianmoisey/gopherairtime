from ubuntu:precise

RUN apt-get update
RUN apt-get install -y python python-dev python-setuptools
RUN apt-get install -y nginx supervisor
RUN apt-get install -y libpq-dev
RUN easy_install pip

RUN pip install uwsgi
RUN pip install virtualenv

# install nginx
RUN apt-get install -y python-software-properties
RUN apt-get update
#RUN add-apt-repository -y ppa:nginx/stable
RUN apt-get install -y sqlite3

# install our code
RUN mkdir -p /srv/wcl/prod/gopherairtime
ADD . /srv/wcl/prod/gopherairtime
RUN virtualenv --no-site-packages /srv/wcl/prod/gopherairtime/ve
RUN /srv/wcl/prod/gopherairtime/ve/bin/pip install -r /srv/wcl/prod/gopherairtime/requirements.pip
RUN /srv/wcl/prod/gopherairtime/ve/bin/python /srv/wcl/prod/gopherairtime/manage.py syncdb --noinput
RUN /srv/wcl/prod/gopherairtime/ve/bin/python /srv/wcl/prod/gopherairtime/manage.py collectstatic --noinput

# setup all the configfiles
RUN echo "daemon off;" >> /etc/nginx/nginx.conf
RUN rm /etc/nginx/sites-enabled/default
RUN ln -s /srv/wcl/prod/gopherairtime/gopherairtime.com.conf /etc/nginx/sites-enabled/
RUN ln -s /srv/wcl/prod/gopherairtime/etc/supervisord.conf /etc/supervisord.conf

EXPOSE 80
CMD ["supervisord", "-n"]
