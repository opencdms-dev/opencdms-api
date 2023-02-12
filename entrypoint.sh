export PYGEOAPI_CONFIG=pygeoapi_config.yml
export PYGEOAPI_OPENAPI=pygeoapi_openapi.yml
export FLASK_APP=opencdms_api.main
pygeoapi openapi generate $PYGEOAPI_CONFIG > $PYGEOAPI_OPENAPI
flask --debug run --host 0.0.0.0 --port 5000
