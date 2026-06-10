FROM nginx:1.27-alpine

# Site config and static assets.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY html/ /usr/share/nginx/html/

EXPOSE 80
