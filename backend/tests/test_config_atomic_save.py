"""测试配置保存的原子性"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from backend.services.config.config_manager import ConfigManager


class TestConfigAtomicSave(unittest.TestCase):
    """测试配置保存失败时不破坏原文件"""

    def test_yaml_dump_failure_preserves_original(self):
        """测试 yaml.dump 失败时保留原文件内容"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.yaml"

            # 创建初始配置文件
            original_data = {"key": "original_value", "important": "data"}
            config_file.write_text(yaml.dump(original_data, allow_unicode=True))

            # 验证原文件存在且内容正确
            self.assertTrue(config_file.exists())
            self.assertEqual(
                yaml.safe_load(config_file.read_text()),
                original_data
            )

            # 尝试保存会导致 yaml.dump 失败的数据
            manager = ConfigManager()

            with patch('yaml.dump') as mock_dump:
                mock_dump.side_effect = OSError('simulated disk full')

                # 保存应该失败并抛出异常
                with self.assertRaises(RuntimeError) as ctx:
                    manager._save_single_config(
                        config_file,
                        {"new": "data"}
                    )

                self.assertIn("保存配置到", str(ctx.exception))
                self.assertIn("失败", str(ctx.exception))

            # 验证原文件内容未被破坏
            self.assertTrue(config_file.exists())
            restored = yaml.safe_load(config_file.read_text())
            self.assertEqual(restored, original_data)

            # 验证没有遗留临时文件
            temp_files = list(Path(tmpdir).glob(".*tmp"))
            self.assertEqual(len(temp_files), 0, f"Found leftover temp files: {temp_files}")

    def test_successful_save_replaces_file(self):
        """测试成功保存时正确替换文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.yaml"

            # 创建初始配置
            original_data = {"version": 1}
            config_file.write_text(yaml.dump(original_data, allow_unicode=True))

            # 保存新数据
            manager = ConfigManager()
            new_data = {"version": 2, "updated": True}
            manager._save_single_config(config_file, new_data)

            # 验证新数据已保存
            self.assertTrue(config_file.exists())
            saved = yaml.safe_load(config_file.read_text())
            self.assertEqual(saved, new_data)

            # 验证没有遗留临时文件
            temp_files = list(Path(tmpdir).glob(".*tmp"))
            self.assertEqual(len(temp_files), 0)

    def test_write_failure_preserves_original(self):
        """测试写入失败时保留原文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.yaml"

            # 创建初始配置
            original_data = {"safe": "content"}
            config_file.write_text(yaml.dump(original_data, allow_unicode=True))

            manager = ConfigManager()

            # 模拟写入过程中的 I/O 错误
            with patch('os.fdopen') as mock_fdopen:
                mock_fdopen.side_effect = IOError('disk error')

                with self.assertRaises(RuntimeError):
                    manager._save_single_config(config_file, {"new": "data"})

            # 验证原文件未被破坏
            self.assertTrue(config_file.exists())
            restored = yaml.safe_load(config_file.read_text())
            self.assertEqual(restored, original_data)

    def test_no_leftover_temp_files_on_any_failure(self):
        """测试任何阶段失败都不会遗留临时文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.yaml"
            config_file.write_text(yaml.dump({"old": "data"}, allow_unicode=True))

            manager = ConfigManager()

            # 测试多种失败场景
            failure_scenarios = [
                ('yaml.dump', yaml.YAMLError('yaml error')),
                ('os.fdopen', IOError('io error')),
            ]

            for patch_target, exception in failure_scenarios:
                with patch(patch_target) as mock_func:
                    mock_func.side_effect = exception

                    with self.assertRaises(RuntimeError):
                        manager._save_single_config(config_file, {"new": "data"})

                    # 验证没有遗留临时文件
                    temp_files = list(Path(tmpdir).glob(".*tmp"))
                    self.assertEqual(
                        len(temp_files), 0,
                        f"Found leftover temp files after {patch_target} failure: {temp_files}"
                    )


if __name__ == '__main__':
    unittest.main()
