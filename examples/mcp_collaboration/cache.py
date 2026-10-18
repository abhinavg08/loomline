"""Disposable demo fixture. ttl_ms is milliseconds; clock() returns seconds."""
import time

class Cache:
    def __init__(self,clock=time.monotonic):self.clock=clock;self.entries={}
    def put(self,key,value,ttl_ms):
        if ttl_ms<0:raise ValueError('ttl_ms must be nonnegative')
        self.entries[key]=(value,self.clock()+ttl_ms)  # The owner-run agents investigate this bug.
    def get(self,key):
        entry=self.entries.get(key)
        if entry is None:return None
        value,expires=entry
        if self.clock()>=expires:
            self.entries.pop(key,None);return None
        return value
