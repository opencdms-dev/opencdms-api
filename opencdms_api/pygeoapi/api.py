import urllib.parse
from datetime import datetime
from typing import Any, Tuple, Union

from pygeoapi import l10n
from pygeoapi.api import (
    API,
    gzip,
    pre_process,
    APIRequest,
    FORMAT_TYPES,
    F_JSON,
    F_HTML,
    LOGGER,
    F_JSONLD,
    OGC_RELTYPES_BASE,
    validate_bbox,
    validate_datetime,
    SYSTEM_LOCALE,
)
from pygeoapi.formatter.base import FormatterSerializationError
from pygeoapi.linked_data import jsonldify, jsonldify_collection, geojson2jsonld
from pygeoapi.plugin import load_plugin, PLUGINS
from pygeoapi.provider.base import (
    ProviderConnectionError,
    ProviderTypeError,
    ProviderQueryError,
    ProviderGenericError,
)
from pygeoapi.util import (
    dategetter,
    filter_dict_by_key_value,
    get_provider_by_type,
    get_provider_default,
    render_j2_template,
    to_json,
    str2bool,
)
from pygeofilter.parsers.ecql import parse as parse_ecql_text


class CustomPyGeoAPI(API):
    def __init__(self, config):
        super().__init__(config)

    @gzip
    @pre_process
    @jsonldify
    def describe_collections(
        self, request: Union[APIRequest, Any], dataset=None
    ) -> Tuple[dict, int, str]:
        """
        Provide collection metadata

        :param request: A request object
        :param dataset: name of collection

        :returns: tuple of headers, status code, content
        """

        if not request.is_valid():
            return self.get_format_exception(request)
        headers = request.get_response_headers()

        fcm = {"collections": [], "links": []}

        collections = filter_dict_by_key_value(
            self.config["resources"], "type", "collection"
        )

        if all([dataset is not None, dataset not in collections.keys()]):
            msg = "Collection not found"
            return self.get_exception(404, headers, request.format, "NotFound", msg)

        if dataset is not None:
            collections_dict = {k: v for k, v in collections.items() if k == dataset}
        else:
            collections_dict = collections

        LOGGER.debug("Creating collections")
        for k, v in collections_dict.items():
            if v.get("visibility", "default") == "hidden":
                LOGGER.debug("Skipping hidden layer: {}".format(k))
                continue
            collection_data = get_provider_default(v["providers"])
            collection_data_type = collection_data["type"]

            collection_data_format = None

            if "format" in collection_data:
                collection_data_format = collection_data["format"]

            collection = {
                "id": k,
                "title": l10n.translate(v["title"], request.locale),
                "description": l10n.translate(v["description"], request.locale),  # noqa
                "keywords": l10n.translate(v["keywords"], request.locale),
                "links": [],
            }

            if v.get("extents"):

                bbox = v["extents"]["spatial"]["bbox"]
                # The output should be an array of bbox, so if the user only
                # provided a single bbox, wrap it in an array.
                if not isinstance(bbox[0], list):
                    bbox = [bbox]
                collection["extent"] = {"spatial": {"bbox": bbox}}

                if "crs" in v["extents"]["spatial"]:
                    collection["extent"]["spatial"]["crs"] = v["extents"]["spatial"][
                        "crs"
                    ]

                t_ext = v.get("extents", {}).get("temporal", {})
                if t_ext:
                    begins = dategetter("begin", t_ext)
                    ends = dategetter("end", t_ext)
                    collection["extent"]["temporal"] = {"interval": [[begins, ends]]}
                    if "trs" in t_ext:
                        collection["extent"]["temporal"]["trs"] = t_ext["trs"]

            for link in l10n.translate(v["links"], request.locale):
                lnk = {
                    "type": link["type"],
                    "rel": link["rel"],
                    "title": l10n.translate(link["title"], request.locale),
                    "href": l10n.translate(link["href"], request.locale),
                }
                if "hreflang" in link:
                    lnk["hreflang"] = l10n.translate(link["hreflang"], request.locale)

                collection["links"].append(lnk)

            # TODO: provide translations
            LOGGER.debug("Adding JSON and HTML link relations")
            collection["links"].append(
                {
                    "type": FORMAT_TYPES[F_JSON],
                    "rel": "root",
                    "title": "The landing page of this server as JSON",
                    "href": "{}?f={}".format(self.config["server"]["url"], F_JSON),
                }
            )
            collection["links"].append(
                {
                    "type": FORMAT_TYPES[F_HTML],
                    "rel": "root",
                    "title": "The landing page of this server as HTML",
                    "href": "{}?f={}".format(self.config["server"]["url"], F_HTML),
                }
            )
            collection["links"].append(
                {
                    "type": FORMAT_TYPES[F_JSON],
                    "rel": request.get_linkrel(F_JSON),
                    "title": "This document as JSON",
                    "href": "{}/{}?f={}".format(self.get_collections_url(), k, F_JSON),
                }
            )
            collection["links"].append(
                {
                    "type": FORMAT_TYPES[F_JSONLD],
                    "rel": request.get_linkrel(F_JSONLD),
                    "title": "This document as RDF (JSON-LD)",
                    "href": "{}/{}?f={}".format(
                        self.get_collections_url(), k, F_JSONLD
                    ),
                }
            )
            collection["links"].append(
                {
                    "type": FORMAT_TYPES[F_HTML],
                    "rel": request.get_linkrel(F_HTML),
                    "title": "This document as HTML",
                    "href": "{}/{}?f={}".format(self.get_collections_url(), k, F_HTML),
                }
            )

            if collection_data_type in ["feature", "record", "tile"]:
                # TODO: translate
                collection["itemType"] = collection_data_type
                LOGGER.debug("Adding feature/record based links")
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSON],
                        "rel": "queryables",
                        "title": "Queryables for this collection as JSON",
                        "href": "{}/{}/queryables?f={}".format(
                            self.get_collections_url(), k, F_JSON
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "queryables",
                        "title": "Queryables for this collection as HTML",
                        "href": "{}/{}queryables?f={}".format(
                            self.get_collections_url(), k, F_HTML
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": "application/geo+json",
                        "rel": "items",
                        "title": "items as GeoJSON",
                        "href": "{}/{}/items?f={}".format(
                            self.get_collections_url(), k, F_JSON
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSONLD],
                        "rel": "items",
                        "title": "items as RDF (GeoJSON-LD)",
                        "href": "{}/{}/items?f={}".format(
                            self.get_collections_url(), k, F_JSONLD
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "items",
                        "title": "Items as HTML",
                        "href": "{}/{}/items?f={}".format(
                            self.get_collections_url(), k, F_HTML
                        ),
                    }
                )

            elif collection_data_type == "coverage":
                # TODO: translate
                LOGGER.debug("Adding coverage based links")
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSON],
                        "rel": "collection",
                        "title": "Detailed Coverage metadata in JSON",
                        "href": "{}/{}?f={}".format(
                            self.get_collections_url(), k, F_JSON
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "collection",
                        "title": "Detailed Coverage metadata in HTML",
                        "href": "{}/{}?f={}".format(
                            self.get_collections_url(), k, F_HTML
                        ),
                    }
                )
                coverage_url = "{}/{}/coverage".format(self.get_collections_url(), k)

                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSON],
                        "rel": "{}/coverage-domainset".format(OGC_RELTYPES_BASE),
                        "title": "Coverage domain set of collection in JSON",
                        "href": "{}/domainset?f={}".format(coverage_url, F_JSON),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "{}/coverage-domainset".format(OGC_RELTYPES_BASE),
                        "title": "Coverage domain set of collection in HTML",
                        "href": "{}/domainset?f={}".format(coverage_url, F_HTML),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSON],
                        "rel": "{}/coverage-rangetype".format(OGC_RELTYPES_BASE),
                        "title": "Coverage range type of collection in JSON",
                        "href": "{}/rangetype?f={}".format(coverage_url, F_JSON),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "{}/coverage-rangetype".format(OGC_RELTYPES_BASE),
                        "title": "Coverage range type of collection in HTML",
                        "href": "{}/rangetype?f={}".format(coverage_url, F_HTML),
                    }
                )
                collection["links"].append(
                    {
                        "type": "application/prs.coverage+json",
                        "rel": "{}/coverage".format(OGC_RELTYPES_BASE),
                        "title": "Coverage data",
                        "href": "{}/{}/coverage?f={}".format(
                            self.get_collections_url(), k, F_JSON
                        ),
                    }
                )
                if collection_data_format is not None:
                    collection["links"].append(
                        {
                            "type": collection_data_format["mimetype"],
                            "rel": "{}/coverage".format(OGC_RELTYPES_BASE),
                            "title": "Coverage data as {}".format(
                                collection_data_format["name"]
                            ),
                            "href": "{}/{}/coverage?f={}".format(
                                self.get_collections_url(),
                                k,
                                collection_data_format["name"],
                            ),
                        }
                    )
                if dataset is not None:
                    LOGGER.debug("Creating extended coverage metadata")
                    try:
                        provider_def = get_provider_by_type(
                            self.config["resources"][k]["providers"], "coverage"
                        )
                        p = load_plugin("provider", provider_def)
                    except ProviderConnectionError:
                        msg = "connection error (check logs)"
                        return self.get_exception(
                            500, headers, request.format, "NoApplicableCode", msg
                        )
                    except ProviderTypeError:
                        pass
                    else:
                        collection["crs"] = [p.crs]
                        collection["domainset"] = p.get_coverage_domainset()
                        collection["rangetype"] = p.get_coverage_rangetype()

            try:
                tile = get_provider_by_type(v["providers"], "tile")
            except ProviderTypeError:
                tile = None

            if tile:
                # TODO: translate
                LOGGER.debug("Adding tile links")
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_JSON],
                        "rel": "tiles",
                        "title": "Tiles as JSON",
                        "href": "{}/{}/tiles?f={}".format(
                            self.get_collections_url(), k, F_JSON
                        ),
                    }
                )
                collection["links"].append(
                    {
                        "type": FORMAT_TYPES[F_HTML],
                        "rel": "tiles",
                        "title": "Tiles as HTML",
                        "href": "{}/{}/tiles?f={}".format(
                            self.get_collections_url(), k, F_HTML
                        ),
                    }
                )

            try:
                edr = get_provider_by_type(v["providers"], "edr")
            except ProviderTypeError:
                edr = None

            if edr and dataset is not None:
                # TODO: translate
                LOGGER.debug("Adding EDR links")
                try:
                    p = load_plugin(
                        "provider",
                        get_provider_by_type(
                            self.config["resources"][dataset]["providers"], "edr"
                        ),
                    )
                    parameters = p.get_fields()
                    if parameters:
                        collection["parameter-names"] = {}
                        for f in parameters["field"]:
                            collection["parameter-names"][f["id"]] = f

                    for qt in p.get_query_types():
                        collection["links"].append(
                            {
                                "type": "application/json",
                                "rel": "data",
                                "title": "{} query for this collection as JSON".format(
                                    qt
                                ),  # noqa
                                "href": "{}/{}/{}?f={}".format(
                                    self.get_collections_url(), k, qt, F_JSON
                                ),
                            }
                        )
                        collection["links"].append(
                            {
                                "type": FORMAT_TYPES[F_HTML],
                                "rel": "data",
                                "title": "{} query for this collection as HTML".format(
                                    qt
                                ),  # noqa
                                "href": "{}/{}/{}?f={}".format(
                                    self.get_collections_url(), k, qt, F_HTML
                                ),
                            }
                        )
                except ProviderConnectionError:
                    msg = "connection error (check logs)"
                    return self.get_exception(
                        500, headers, request.format, "NoApplicableCode", msg
                    )
                except ProviderTypeError:
                    pass

            if dataset is not None and k == dataset:
                fcm = collection
                break

            fcm["collections"].append(collection)

        if dataset is None:
            # TODO: translate
            fcm["links"].append(
                {
                    "type": FORMAT_TYPES[F_JSON],
                    "rel": request.get_linkrel(F_JSON),
                    "title": "This document as JSON",
                    "href": "{}?f={}".format(self.get_collections_url(), F_JSON),
                }
            )
            fcm["links"].append(
                {
                    "type": FORMAT_TYPES[F_JSONLD],
                    "rel": request.get_linkrel(F_JSONLD),
                    "title": "This document as RDF (JSON-LD)",
                    "href": "{}?f={}".format(self.get_collections_url(), F_JSONLD),
                }
            )
            fcm["links"].append(
                {
                    "type": FORMAT_TYPES[F_HTML],
                    "rel": request.get_linkrel(F_HTML),
                    "title": "This document as HTML",
                    "href": "{}?f={}".format(self.get_collections_url(), F_HTML),
                }
            )

        if request.format == F_HTML:  # render
            fcm["collections_path"] = self.get_collections_url()
            if dataset is not None:
                content = render_j2_template(
                    self.config, "collections/collection.html", fcm, request.locale
                )
            else:
                content = render_j2_template(
                    self.config, "collections/index.html", fcm, request.locale
                )

            return headers, 200, content

        if request.format == F_JSONLD:
            jsonld = self.fcmld.copy()
            if dataset is not None:
                jsonld["dataset"] = jsonldify_collection(self, fcm, request.locale)
            else:
                jsonld["dataset"] = [
                    jsonldify_collection(self, c, request.locale)
                    for c in fcm.get("collections", [])
                ]
            return headers, 200, to_json(jsonld, self.pretty_print)

        return headers, 200, to_json(fcm, self.pretty_print)

    @gzip
    @pre_process
    @jsonldify
    def get_collection_queryables(
        self, request: Union[APIRequest, Any], dataset=None
    ) -> Tuple[dict, int, str]:
        """
        Provide collection queryables

        :param request: A request object
        :param dataset: name of collection

        :returns: tuple of headers, status code, content
        """

        if not request.is_valid():
            return self.get_format_exception(request)
        headers = request.get_response_headers()

        if any([dataset is None, dataset not in self.config["resources"].keys()]):
            msg = "Collection not found"
            return self.get_exception(404, headers, request.format, "NotFound", msg)

        LOGGER.debug("Creating collection queryables")
        try:
            LOGGER.debug("Loading feature provider")
            p = load_plugin(
                "provider",
                get_provider_by_type(
                    self.config["resources"][dataset]["providers"], "feature"
                ),
            )
        except ProviderTypeError:
            LOGGER.debug("Loading record provider")
            p = load_plugin(
                "provider",
                get_provider_by_type(
                    self.config["resources"][dataset]["providers"], "record"
                ),
            )
        except ProviderConnectionError:
            msg = "connection error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )
        except ProviderQueryError:
            msg = "query error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )

        queryables = {
            "type": "object",
            "title": l10n.translate(
                self.config["resources"][dataset]["title"], request.locale
            ),
            "properties": {},
            "$schema": "http://json-schema.org/draft/2019-09/schema",
            "$id": "{}/{}/queryables".format(self.get_collections_url(), dataset),
        }

        if p.fields and (hasattr(p, "spatial") and p.spatial):
            queryables["properties"]["geometry"] = {
                "$ref": "https://geojson.org/schema/Geometry.json"
            }

        for k, v in p.fields.items():
            show_field = False
            if p.properties:
                if k in p.properties:
                    show_field = True
            else:
                show_field = True

            if show_field:
                queryables["properties"][k] = {"title": k, "type": v["type"]}
                if "values" in v:
                    queryables["properties"][k]["enum"] = v["values"]

        if request.format == F_HTML:  # render
            queryables["title"] = l10n.translate(
                self.config["resources"][dataset]["title"], request.locale
            )

            queryables["collections_path"] = self.get_collections_url()

            content = render_j2_template(
                self.config, "collections/queryables.html", queryables, request.locale
            )

            return headers, 200, content

        headers["Content-Type"] = "application/schema+json"

        return headers, 200, to_json(queryables, self.pretty_print)

    @gzip
    @pre_process
    def get_collection_items(
        self, request: Union[APIRequest, Any], dataset
    ) -> Tuple[dict, int, str]:
        """
        Queries collection

        :param request: A request object
        :param dataset: dataset name

        :returns: tuple of headers, status code, content
        """

        if not request.is_valid(PLUGINS["formatter"].keys()):
            return self.get_format_exception(request)

        # Set Content-Language to system locale until provider locale
        # has been determined
        headers = request.get_response_headers(SYSTEM_LOCALE)

        properties = []
        reserved_fieldnames = [
            "bbox",
            "f",
            "lang",
            "limit",
            "offset",
            "resulttype",
            "datetime",
            "sortby",
            "properties",
            "skipGeometry",
            "q",
            "filter",
            "filter-lang",
        ]

        collections = filter_dict_by_key_value(
            self.config["resources"], "type", "collection"
        )

        if dataset not in collections.keys():
            msg = "Collection not found"
            return self.get_exception(404, headers, request.format, "NotFound", msg)

        LOGGER.debug("Processing query parameters")

        LOGGER.debug("Processing offset parameter")
        try:
            offset = int(request.params.get("offset"))
            if offset < 0:
                msg = "offset value should be positive or zero"
                return self.get_exception(
                    400, headers, request.format, "InvalidParameterValue", msg
                )
        except TypeError as err:
            LOGGER.warning(err)
            offset = 0
        except ValueError:
            msg = "offset value should be an integer"
            return self.get_exception(
                400, headers, request.format, "InvalidParameterValue", msg
            )

        LOGGER.debug("Processing limit parameter")
        try:
            limit = int(request.params.get("limit"))
            # TODO: We should do more validation, against the min and max
            #       allowed by the server configuration
            if limit <= 0:
                msg = "limit value should be strictly positive"
                return self.get_exception(
                    400, headers, request.format, "InvalidParameterValue", msg
                )
        except TypeError as err:
            LOGGER.warning(err)
            limit = int(self.config["server"]["limit"])
        except ValueError:
            msg = "limit value should be an integer"
            return self.get_exception(
                400, headers, request.format, "InvalidParameterValue", msg
            )

        resulttype = request.params.get("resulttype") or "results"

        LOGGER.debug("Processing bbox parameter")

        bbox = request.params.get("bbox")

        if bbox is None:
            bbox = []
        else:
            try:
                bbox = validate_bbox(bbox)
            except ValueError as err:
                msg = str(err)
                return self.get_exception(
                    400, headers, request.format, "InvalidParameterValue", msg
                )

        LOGGER.debug("Processing datetime parameter")
        datetime_ = request.params.get("datetime")
        try:
            datetime_ = validate_datetime(collections[dataset]["extents"], datetime_)
        except KeyError as e:
            if e == "extents":
                pass
        except ValueError as err:
            msg = str(err)
            return self.get_exception(
                400, headers, request.format, "InvalidParameterValue", msg
            )

        LOGGER.debug("processing q parameter")
        q = request.params.get("q") or None

        LOGGER.debug("Loading provider")

        try:
            provider_def = get_provider_by_type(
                collections[dataset]["providers"], "feature"
            )
            p = load_plugin("provider", provider_def)
        except ProviderTypeError:
            try:
                provider_def = get_provider_by_type(
                    collections[dataset]["providers"], "record"
                )
                p = load_plugin("provider", provider_def)
            except ProviderTypeError:
                msg = "Invalid provider type"
                return self.get_exception(
                    400, headers, request.format, "NoApplicableCode", msg
                )
        except ProviderConnectionError:
            msg = "connection error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )
        except ProviderQueryError:
            msg = "query error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )

        LOGGER.debug("processing property parameters")
        for k, v in request.params.items():
            if k not in reserved_fieldnames and k in list(p.fields.keys()):
                LOGGER.debug("Adding property filter {}={}".format(k, v))
                properties.append((k, v))

        LOGGER.debug("processing sort parameter")
        val = request.params.get("sortby")

        if val is not None:
            sortby = []
            sorts = val.split(",")
            for s in sorts:
                prop = s
                order = "+"
                if s[0] in ["+", "-"]:
                    order = s[0]
                    prop = s[1:]

                if prop not in p.fields.keys():
                    msg = "bad sort property"
                    return self.get_exception(
                        400, headers, request.format, "InvalidParameterValue", msg
                    )

                sortby.append({"property": prop, "order": order})
        else:
            sortby = []

        LOGGER.debug("processing properties parameter")
        val = request.params.get("properties")

        if val is not None:
            select_properties = val.split(",")
            properties_to_check = set(p.properties) | set(p.fields.keys())

            if len(list(set(select_properties) - set(properties_to_check))) > 0:
                msg = "unknown properties specified"
                return self.get_exception(
                    400, headers, request.format, "InvalidParameterValue", msg
                )
        else:
            select_properties = []

        LOGGER.debug("processing skipGeometry parameter")
        val = request.params.get("skipGeometry")
        if val is not None:
            skip_geometry = str2bool(val)
        else:
            skip_geometry = False

        LOGGER.debug("processing filter parameter")
        cql_text = request.params.get("filter")
        if cql_text is not None:
            try:
                filter_ = parse_ecql_text(cql_text)
            except Exception as err:
                LOGGER.error(err)
                msg = f"Bad CQL string : {cql_text}"
                return self.get_exception(
                    400, headers, request.format, "InvalidParameterValue", msg
                )
        else:
            filter_ = None

        LOGGER.debug("Processing filter-lang parameter")
        filter_lang = request.params.get("filter-lang")
        # Currently only cql-text is handled, but it is optional
        if filter_lang not in [None, "cql-text"]:
            msg = "Invalid filter language"
            return self.get_exception(
                400, headers, request.format, "InvalidParameterValue", msg
            )

        # Get provider locale (if any)
        prv_locale = l10n.get_plugin_locale(provider_def, request.raw_locale)

        LOGGER.debug("Querying provider")
        LOGGER.debug("offset: {}".format(offset))
        LOGGER.debug("limit: {}".format(limit))
        LOGGER.debug("resulttype: {}".format(resulttype))
        LOGGER.debug("sortby: {}".format(sortby))
        LOGGER.debug("bbox: {}".format(bbox))
        LOGGER.debug("datetime: {}".format(datetime_))
        LOGGER.debug("properties: {}".format(properties))
        LOGGER.debug("select properties: {}".format(select_properties))
        LOGGER.debug("skipGeometry: {}".format(skip_geometry))
        LOGGER.debug("language: {}".format(prv_locale))
        LOGGER.debug("q: {}".format(q))
        LOGGER.debug("cql_text: {}".format(cql_text))
        LOGGER.debug("filter-lang: {}".format(filter_lang))

        try:
            content = p.query(
                offset=offset,
                limit=limit,
                resulttype=resulttype,
                bbox=bbox,
                datetime_=datetime_,
                properties=properties,
                sortby=sortby,
                select_properties=select_properties,
                skip_geometry=skip_geometry,
                q=q,
                language=prv_locale,
                filterq=filter_,
            )
        except ProviderConnectionError as err:
            LOGGER.error(err)
            msg = "connection error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )
        except ProviderQueryError as err:
            LOGGER.error(err)
            msg = "query error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )
        except ProviderGenericError as err:
            LOGGER.error(err)
            msg = "generic error (check logs)"
            return self.get_exception(
                500, headers, request.format, "NoApplicableCode", msg
            )

        serialized_query_params = ""
        for k, v in request.params.items():
            if k not in ("f", "offset"):
                serialized_query_params += "&"
                serialized_query_params += urllib.parse.quote(k, safe="")
                serialized_query_params += "="
                serialized_query_params += urllib.parse.quote(str(v), safe=",")

        # TODO: translate titles
        uri = "{}/{}/items".format(self.get_collections_url(), dataset)
        content["links"] = [
            {
                "type": "application/geo+json",
                "rel": request.get_linkrel(F_JSON),
                "title": "This document as GeoJSON",
                "href": "{}?f={}{}".format(uri, F_JSON, serialized_query_params),
            },
            {
                "rel": request.get_linkrel(F_JSONLD),
                "type": FORMAT_TYPES[F_JSONLD],
                "title": "This document as RDF (JSON-LD)",
                "href": "{}?f={}{}".format(uri, F_JSONLD, serialized_query_params),
            },
            {
                "type": FORMAT_TYPES[F_HTML],
                "rel": request.get_linkrel(F_HTML),
                "title": "This document as HTML",
                "href": "{}?f={}{}".format(uri, F_HTML, serialized_query_params),
            },
        ]

        if offset > 0:
            prev = max(0, offset - limit)
            content["links"].append(
                {
                    "type": "application/geo+json",
                    "rel": "prev",
                    "title": "items (prev)",
                    "href": "{}?offset={}{}".format(uri, prev, serialized_query_params),
                }
            )

        if len(content["features"]) == limit:
            next_ = offset + limit
            content["links"].append(
                {
                    "type": "application/geo+json",
                    "rel": "next",
                    "title": "items (next)",
                    "href": "{}?offset={}{}".format(
                        uri, next_, serialized_query_params
                    ),
                }
            )

        content["links"].append(
            {
                "type": FORMAT_TYPES[F_JSON],
                "title": l10n.translate(collections[dataset]["title"], request.locale),
                "rel": "collection",
                "href": uri,
            }
        )

        content["timeStamp"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Set response language to requested provider locale
        # (if it supports language) and/or otherwise the requested pygeoapi
        # locale (or fallback default locale)
        l10n.set_response_language(headers, prv_locale, request.locale)

        if request.format == F_HTML:  # render
            # For constructing proper URIs to items

            content["items_path"] = uri
            content["dataset_path"] = "/".join(uri.split("/")[:-1])
            content["collections_path"] = self.get_collections_url()

            content["offset"] = offset

            content["id_field"] = p.id_field
            if p.uri_field is not None:
                content["uri_field"] = p.uri_field
            if p.title_field is not None:
                content["title_field"] = l10n.translate(p.title_field, request.locale)
                # If title exists, use it as id in html templates
                content["id_field"] = content["title_field"]
            content = render_j2_template(
                self.config, "collections/items/index.html", content, request.locale
            )
            return headers, 200, content
        elif request.format == "csv":  # render
            formatter = load_plugin("formatter", {"name": "CSV", "geom": True})

            try:
                content = formatter.write(
                    data=content,
                    options={
                        "provider_def": get_provider_by_type(
                            collections[dataset]["providers"], "feature"
                        )
                    },
                )
            except FormatterSerializationError as err:
                LOGGER.error(err)
                msg = "Error serializing output"
                return self.get_exception(
                    500, headers, request.format, "NoApplicableCode", msg
                )

            headers["Content-Type"] = "{}; charset={}".format(
                formatter.mimetype, self.config["server"]["encoding"]
            )

            if p.filename is None:
                filename = "{}.csv".format(dataset)
            else:
                filename = "{}".format(p.filename)

            cd = 'attachment; filename="{}"'.format(filename)
            headers["Content-Disposition"] = cd

            return headers, 200, content

        elif request.format == F_JSONLD:
            content = geojson2jsonld(
                self.config, content, dataset, id_field=(p.uri_field or "id")
            )

        return headers, 200, to_json(content, self.pretty_print)
