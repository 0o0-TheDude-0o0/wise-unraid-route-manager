import subprocess
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT=Path(__file__).parents[1]


class PackagingTests(unittest.TestCase):
    def test_unraid_template_requires_tls_and_no_fixed_ip(self):
        root=ET.parse(ROOT/"templates"/"wise-route-manager.xml").getroot()
        self.assertEqual(root.findtext("Network"),"br0")
        self.assertFalse((root.findtext("MyIP") or "").strip())
        self.assertIn("preview-and-approve",root.findtext("Overview"))
        targets={item.attrib.get("Target") for item in root.findall("Config")}
        self.assertIn("/config/tls/tls.crt",targets)
        self.assertIn("/config/tls/tls.key",targets)

    def test_lite_template_explains_safe_onboarding(self):
        root=ET.parse(ROOT/"templates"/"wise-route-manager-lite.xml").getroot()
        self.assertIn("read-only",root.findtext("Overview"))
        descriptions={item.attrib["Target"]: item.attrib.get("Description","") for item in root.findall("Config")}
        self.assertIn("Recommended",descriptions["WISE_ENABLE_PROVIDER_MUTATIONS"])
        self.assertIn("discovered proxies",descriptions["443"])

    def test_unraid_page_has_ready_and_setup_guidance(self):
        page=(ROOT/"unraid-plugin/usr/local/emhttp/plugins/wise.route.manager/WiseRouteManager.page").read_text()
        self.assertIn("Finish the connection",page)
        self.assertIn("Open Route Manager",page)
        self.assertIn("Preview first",page)
        self.assertIn("navigator.clipboard",page)

    def test_release_assets_are_valid_and_parameterized(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(ROOT/"scripts"/"build-release-assets.sh"),"0.1.0","example","wise-route-manager",directory],cwd=ROOT,check=True,capture_output=True,text=True)
            output=Path(directory); plugin=ET.parse(output/"wise.route.manager.plg").getroot(); template=ET.parse(output/"wise-route-manager.xml").getroot(); lite=ET.parse(output/"wise-route-manager-lite.xml").getroot()
            self.assertEqual(plugin.attrib["version"],"0.1.0")
            self.assertIn("example/wise-route-manager",plugin.attrib["pluginURL"])
            self.assertEqual(template.findtext("Repository"),"ghcr.io/example/wise-unraid-route-manager:latest")
            self.assertEqual(lite.findtext("Name"),"Wise Route Manager Lite")
            self.assertEqual(next(item for item in lite.findall("Config") if item.attrib.get("Target")=="WISE_EDITION").attrib.get("Default"),"lite")
            self.assertTrue((output/"SHA256SUMS").exists())


if __name__ == "__main__": unittest.main()
