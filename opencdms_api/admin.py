import opencdms_cdm
from flask_admin.contrib.sqla import ModelView
from opencdms_api.db import db

views = (
    ModelView(opencdms_cdm.Observation_type, db.session),
    ModelView(opencdms_cdm.Feature_type, db.session),
    ModelView(opencdms_cdm.Observed_property, db.session),
    ModelView(opencdms_cdm.Observing_procedure, db.session),
    ModelView(opencdms_cdm.Record_status, db.session),
    ModelView(opencdms_cdm.Stations, db.session),
    ModelView(opencdms_cdm.Sensors, db.session),
    ModelView(opencdms_cdm.Observations, db.session),
    ModelView(opencdms_cdm.Collections, db.session),
    ModelView(opencdms_cdm.Features, db.session),
)
