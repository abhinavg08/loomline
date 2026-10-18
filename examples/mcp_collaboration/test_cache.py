import unittest
from cache import Cache

class Clock:
    def __init__(self):self.now=40.0
    def __call__(self):return self.now

class CacheTests(unittest.TestCase):
    def setUp(self):self.clock=Clock();self.cache=Cache(self.clock)
    def test_entry_expires_after_one_second(self):
        self.cache.put('job','pending',1000);self.clock.now+=1.5
        self.assertIsNone(self.cache.get('job'))
    def test_value_before_expiry(self):
        self.cache.put('job','pending',1000);self.clock.now+=.999
        self.assertEqual(self.cache.get('job'),'pending')
    def test_exact_deadline_expires(self):
        self.cache.put('job','pending',1000);self.clock.now+=1
        self.assertIsNone(self.cache.get('job'))
    def test_zero_ttl(self):
        self.cache.put('zero','gone',0);self.assertIsNone(self.cache.get('zero'))
    def test_missing_and_negative(self):
        self.assertIsNone(self.cache.get('missing'))
        with self.assertRaises(ValueError):self.cache.put('bad','x',-1)
    def test_overwrite_and_independent_keys(self):
        self.cache.put('a','old',1000);self.cache.put('a','new',2000);self.cache.put('b','other',4000)
        self.clock.now+=2
        self.assertIsNone(self.cache.get('a'));self.assertEqual(self.cache.get('b'),'other')

if __name__=='__main__':unittest.main()
