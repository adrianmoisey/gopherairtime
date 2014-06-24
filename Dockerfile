from ubuntu:precise

run apt-get update
run apt-get install -y python python-dev python-setuptools
run apt-get install -y nginx supervisor
run easy_install pip

run pip install uwsgi
run pip install virtualenv

# install nginx
run apt-get install -y python-software-properties
run apt-get update
#RUN add-apt-repository -y ppa:nginx/stable
run apt-get install -y sqlite3

# install our code
run mkdir -p /srv/wcl/prod/gopherairtime
add . /srv/wcl/prod/gopherairtime
RUN virtualenv --no-site-packages /srv/wcl/prod/gopherairtime/ve
run /srv/wcl/prod/gopherairtime/ve/bin/pip install -r /srv/wcl/prod/gopherairtime/requirements.pip

# setup all the configfiles
#run echo "daemon off;" >> /etc/nginx/nginx.conf
#run rm /etc/nginx/sites-enabled/default
#run ln -s /srv/wcl/prod/gopherairtime/etc/nginx.conf /etc/nginx/sites-enabled/
run ln -s /srv/wcl/prod/gopherairtime/etc/supervisord.conf /etc/supervisord.conf
run ln -s /srv/wcl/prod/gopherairtime/etc/conf.d/django.conf /etc/supervisord/conf.d/django.conf

expose 8000
cmd ["supervisord", "-n"]
