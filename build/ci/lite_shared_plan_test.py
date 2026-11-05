#!/usr/bin/env python3
"""Check that shared prerequisites are built once in the plan."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import lite_shared_plan


class SharedPlanTest(unittest.TestCase):
    def test_shared_object_is_removed_from_every_parallel_group(self):
        ninja = os.environ.get("LITE_NINJA_TEST_BINARY") or shutil.which("ninja")
        if not ninja:
            self.skipTest("ninja is required")
        test_root = Path(__file__).resolve().parents[2] / ".git" / "lite-validation"
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as temporary:
            build = Path(temporary)
            (build / 'fakecc.py').write_text('''\
from pathlib import Path
import sys
out = sys.argv[sys.argv.index('-o') + 1]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(out)
with open('compiled.log', 'a') as log:
    log.write(out + '\\n')
''')
            (build / 'shared.c').write_text('shared')
            for index in range(5):
                (build / f'leaf{index}.c').write_text(f'leaf {index}')
            graph = ['rule cc\n  command = python3 fakecc.py -c $in -o $out\n',
                     'build obj/shared.o: cc shared.c\n']
            for index in range(5):
                graph.append(f'build obj/leaf{index}.o: cc leaf{index}.c | obj/shared.o\n')
            graph.append('build brave: phony ' + ' '.join(
                f'obj/leaf{index}.o' for index in range(5)) + '\n')
            (build / "build.ninja").write_text(''.join(graph))
            report = lite_shared_plan.plan(Path(ninja), build)
            self.assertEqual(report["shared_object_count"], 1)
            self.assertEqual(report["bootstrap"]["compiler_commands"], 1)
            self.assertEqual(report["groups_after"]["compiler_commands"]["repeated"], 0)
            self.assertEqual(report["groups_after"]["compiler_commands"]["executions"], 5)
            self.assertIn('obj/shared.o', (build / 'brave_lite_shared.ninja').read_text())
            subprocess.run([ninja, '-C', str(build), '-f', 'brave_lite_shared.ninja',
                            'brave_lite_shared'], check=True, capture_output=True)
            self.assertEqual((build / 'compiled.log').read_text().splitlines(), ['obj/shared.o'])
            for index in range(5):
                clone = build.parent / f'{build.name}-clone-{index}'
                shutil.copytree(build, clone)
                self.addCleanup(shutil.rmtree, clone)
                subprocess.run([ninja, '-C', str(clone), '-f', 'brave_lite_graph.ninja',
                                f'brave_lite_group_{index + 1}'], check=True, capture_output=True)
                compiled = (clone / 'compiled.log').read_text().splitlines()
                self.assertEqual(compiled.count('obj/shared.o'), 1)
                self.assertEqual(len(compiled), 2)


if __name__ == "__main__":
    unittest.main()
