import copy, sys, pathlib, unittest, datetime
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from student_run import validate_report, principal_id
from dispatch_guard import allowed
from publisher import encrypt, decrypt
from cryptography.exceptions import InvalidTag

class StudentBoundary(unittest.TestCase):
    def setUp(self):
        self.principal=principal_id('student-demo')
        self.report={'schema':1,'audience':'student','principal':self.principal,'accounts':{'demo':{'role':'student'}},'digest':{'actions':[],'observations':[]}}
    def test_student_only(self): validate_report(self.report,self.principal,'demo')
    def test_parent_or_other_child_is_rejected(self):
        for field,value in [('audience','parent'),('principal',principal_id('someone-else')),('accounts',{'demo':{'role':'student'},'sibling':{'role':'parent'}}),('digest',{'actions':[{'child':'sibling'}]})]:
            report=copy.deepcopy(self.report);report[field]=value
            with self.assertRaises(ValueError):validate_report(report,self.principal,'demo')
    def test_passwords_do_not_cross(self):
        encrypted=encrypt(self.report,'student-demo-pass')
        self.assertEqual(decrypt(encrypted,'student-demo-pass'),self.report)
        with self.assertRaises(InvalidTag):decrypt(encrypted,'parent-demo-pass')
    def test_cooldown_covers_failed_attempts(self):
        now=datetime.datetime.now(datetime.timezone.utc)
        self.assertFalse(allowed([{'id':1,'created_at':(now-datetime.timedelta(seconds=20)).isoformat()}],2,now))
        self.assertTrue(allowed([{'id':1,'created_at':(now-datetime.timedelta(seconds=301)).isoformat()}],2,now))
if __name__=='__main__':unittest.main()
