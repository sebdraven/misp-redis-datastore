#!/usr/bin/env python
# -*- coding: utf-8 -*-

from sqlalchemy.ext.automap import automap_base
from sqlalchemy import create_engine
from sqlalchemy.schema import MetaData, Table
from sqlalchemy.sql import select
from Crypto.Hash import SHA256
from redis import StrictRedis
from config import user, password, host, dbname, redis_socket


class MispMySQLConnector(object):

    def __init__(self):
        Base = automap_base()
        engine = create_engine('mysql://{}:{}@{}/{}'.format(user, password, host, dbname))

        # reflect the tables
        Base.prepare(engine, reflect=True)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        self.connection = engine.connect()
        self.events = Table("events", metadata, autoload=True)
        self.users = Table("users", metadata, autoload=True)
        self.attributes = Table("attributes", metadata, autoload=True)

        self.r = StrictRedis(unix_socket_path=redis_socket)

    # ####### Other functions ########

    def import_auth(self):
        users = self.connection.execute(select([self.users]))
        for u in users:
            self.r.set(u['authkey'], u['org_id'])

    # ####### Helpers ########

    def __get_all_event_uuid(self):
        # Build hashtable of event ID - event UUID
        eid_uuid = {}
        results = self.connection.execute(select([self.events]))
        for event in results:
            eid_uuid[event['id']] = event['uuid']
            self.r.hset('uuid_id', event['uuid'], event['id'])
        return eid_uuid

    # ####### Cache all attributes for fast access. Auth preserved. ########

    def _add_hash(self, event_uuid, value1, value2='', orgid=None):
        if orgid:
            key = '{}:'.format(orgid)
        else:
            key = ''
        hash_value = SHA256.new(value1.lower()).hexdigest()
        self.r.sadd(key + hash_value, event_uuid)
        if value2:
            hash_value = SHA256.new(value2.lower()).hexdigest()
            self.r.sadd(key + hash_value, event_uuid)

    def cache_attributes(self):
        eid_uuid = self.__get_all_event_uuid()
        attributes = self.connection.execute(select([self.attributes]))
        for a in attributes:
            orgid = None
            if a['distribution'] == 0:
                # Limited distribution (this org only)
                result = self.connection.execute(select([self.events.c.org_id]).where(self.events.c.id == a['event_id']))
                for e in result:
                    orgid = e.org_id
            uuid = eid_uuid.get(a['event_id'])
            if not uuid:
                continue
            self._add_hash(uuid, a['value1'], a['value2'], orgid)
