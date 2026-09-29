"""Library filter attributes.

The filters are client-side, so what matters server-side is that every row carries the
data each filter keys on — with the right value for exercises where the field is
ABSENT, which is where the cable-height filter first went wrong.
"""
import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402

EXERCISES = [
    # A cable move on a 45-degree bench.
    {"id": 1, "title": "Incline Press", "trainingPartId2": 11, "tabName": "Training",
     "outPosition": 3, "foldingStoolAngle": "45°", "accessories": "5", "category_id": 1,
     "mainMuscleGroupName": "Pecs", "mainMuscleGroupList": [{"muscleGroupName": "Pecs"}],
     "auxiliaryMuscleGroupList": [{"muscleGroupName": "Triceps"}], "equipment_name": "Handles"},
    # A mat move: no cable at all — the field is MISSING, not null.
    {"id": 2, "title": "Child Pose", "trainingPartId2": 13, "tabName": "Pilates-Mat",
     "foldingStoolAngle": "", "accessories": "", "category_id": 20,
     "mainMuscleGroupName": "Lats", "mainMuscleGroupList": [{"muscleGroupName": "Lats"}],
     "auxiliaryMuscleGroupList": [], "equipment_name": "Standard"},
    # Cable at the top position, which is 0 — and 0 must not be read as "absent".
    {"id": 3, "title": "Barbell Upper Pull", "trainingPartId2": 13, "tabName": "Recovery",
     "outPosition": 0, "foldingStoolAngle": "", "accessories": "4", "category_id": 7,
     "mainMuscleGroupName": "Lats", "mainMuscleGroupList": [{"muscleGroupName": "Lats"}],
     "auxiliaryMuscleGroupList": [{"muscleGroupName": "Biceps"}], "equipment_name": "Barbell"},
]


class TestLibraryFilterData(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def render(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_library', return_value=EXERCISES), \
             mock.patch.object(app_module.client, 'get_accessories',
                               return_value=[{"id": 4, "name": "Barbell"}, {"id": 5, "name": "Handles"}]), \
             mock.patch.object(app_module.client, 'get_categories', return_value=[]), \
             mock.patch.object(app_module, '_avoided_list_safe', return_value=[]):
            return self.client.get('/library').get_data(as_text=True)

    def test_a_missing_cable_field_renders_as_none_not_empty(self):
        # `Undefined is not none` is TRUE in Jinja, so the absent key rendered as "" and
        # the "No cable" filter matched nothing at all.
        html = self.render()
        self.assertIn('data-cable="none"', html)
        self.assertNotIn('data-cable=""', html)

    def test_cable_position_zero_is_kept(self):
        # Top of the mast is 0; treating it as falsy would hide those exercises.
        self.assertIn('data-cable="0"', self.render())

    def test_bench_angle_loses_the_degree_sign_and_absent_means_none(self):
        html = self.render()
        self.assertIn('data-bench="45"', html)
        self.assertIn('data-bench="none"', html)

    def test_type_comes_from_the_librarys_own_tab_names(self):
        html = self.render()
        for value in ('data-type="training"', 'data-type="pilates-mat"', 'data-type="recovery"'):
            self.assertIn(value, html)

    def test_main_and_assisting_muscles_are_carried_separately(self):
        # "Primary only" needs the main list alone; the combined list drives the default.
        html = self.render()
        self.assertIn('data-main-muscles="pecs"', html)
        self.assertIn('data-muscles="pecs,triceps"', html)

    def test_every_filter_row_is_rendered(self):
        html = self.render()
        for row in ('muscleName', 'type', 'cable', 'bench'):
            self.assertIn(f'data-filter-row="{row}"', html)
        self.assertIn('id="primaryOnly"', html)
        self.assertIn('id="activeChips"', html)


if __name__ == "__main__":
    unittest.main()
