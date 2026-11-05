#!/usr/bin/env python3
"""Test that browser object partitions are exhaustive and disjoint."""

import unittest

import lite_partition_graph


class PartitionTest(unittest.TestCase):
    def test_objects_are_disjoint_and_deterministic(self):
        objects = [f"obj/{index // 250}/file{index:04}.o" for index in range(1500)]
        groups = lite_partition_graph.partition(objects)
        self.assertEqual(groups, lite_partition_graph.partition(objects))
        for shards in groups.values():
            flattened = [name for shard in shards for name in shard]
            self.assertEqual(len(flattened), len(set(flattened)))
            self.assertEqual(set(flattened), set(objects))
            self.assertEqual(len(shards), 5)

    def test_graph_parser_ignores_rules_and_non_objects(self):
        lines = ['"0x1" [label="obj/one.o"]',
                 '"0x2" [label="cxx", shape=ellipse]',
                 '"0x3" [label="../../one.cc"]',
                 '"0x1" [label="obj/one.o"]',
                 '"0x4" [label="obj/f16_arch=armv8.2-a+fp16/file.o"]']
        self.assertEqual(lite_partition_graph.graph_objects(lines),
                         ["obj/f16_arch=armv8.2-a+fp16/file.o", "obj/one.o"])

    def test_small_single_directory_uses_all_runners(self):
        objects = [f"obj/one/file{index}.o" for index in range(10)]
        for shards in lite_partition_graph.partition(objects).values():
            self.assertTrue(all(shard for shard in shards))


if __name__ == "__main__":
    unittest.main()
