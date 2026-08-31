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
        self.assertEqual(next(item for item in root.findall("Config") if item.attrib.get("Target")=="/config").attrib.get("Default"),"")
        self.assertEqual(next(item for item in root.findall("Config") if item.attrib.get("Target")=="/config").attrib.get("Mode"),"rw,slave")
        self.assertIn("Default appdata storage location",descriptions["/config"])
        self.assertIn("Recommended",descriptions["WISE_ENABLE_PROVIDER_MUTATIONS"])
        self.assertIn("discovered proxies",descriptions["443"])

    def test_unraid_page_has_ready_and_setup_guidance(self):
        page=(ROOT/"unraid-plugin/usr/local/emhttp/plugins/wise.route.manager/WiseRouteManager.page").read_text()
        self.assertIn("Create the Lite container",page)
        self.assertIn("Open Route Manager",page)
        self.assertIn("Preview first",page)
        self.assertIn("navigator.clipboard",page)
        self.assertIn("DEFAULT_APPDATA",page)
        self.assertIn("APPDATA_MOUNT_MODE",page)
        self.assertIn("Detected appdata storage",page)
        self.assertIn('Type="xmenu"',page)
        self.assertIn("wrm-ref-details",page)
        self.assertIn("wrm-ref-row",page)
        self.assertIn('colspan="4"',page)
        self.assertIn("foundPaths",page)
        self.assertIn("wrm_count_label",page)
        self.assertIn("'ref', 'refs'",page)
        self.assertIn("'path', 'paths'",page)
        self.assertIn("pathCount",page)
        self.assertIn("wrm-container-install.sh",page)
        self.assertIn("Create and start container",page)
        self.assertIn("docker inspect -f",page)
        self.assertIn("containerRunning",page)
        self.assertIn("wrm-path-choice",page)
        self.assertIn("Custom path",page)
        self.assertIn("wrm-ip-suggest.sh",page)
        self.assertIn("APP_URL",page)
        scan=(ROOT/"unraid-plugin/usr/local/emhttp/plugins/wise.route.manager/wrm-storage-scan.sh").read_text()
        installer_doinst=(ROOT/"unraid-plugin/install/doinst.sh").read_text()
        self.assertIn("chmod 0755 /usr/local/emhttp/plugins/wise.route.manager/wrm-*.sh",installer_doinst)
        self.assertIn("DOCKER_APP_CONFIG_PATH",scan)
        self.assertIn("Read/Write - Slave",scan)
        self.assertIn("docker inspect",scan)
        self.assertIn("storage_probe_path",scan)
        self.assertIn("device=${device%%[*}",scan)
        self.assertIn("drive=\"User share\"",scan)
        self.assertIn("drive=\"Pool/share managed\"",scan)
        self.assertIn("filesystem=\"Pool/share managed\"",scan)
        self.assertIn("paths[root]",scan)
        self.assertIn("found_paths",scan)
        self.assertIn("gsub(/[`.,;:)",scan)
        installer=(ROOT/"unraid-plugin/usr/local/emhttp/plugins/wise.route.manager/wrm-container-install.sh").read_text()
        self.assertIn("docker run -d",installer)
        self.assertIn("--network br0",installer)
        self.assertIn("--ip",installer)
        self.assertIn("net.unraid.docker.managed=dockerman",installer)
        self.assertIn("net.unraid.docker.webui",installer)
        self.assertIn("net.unraid.docker.icon",installer)
        self.assertTrue((ROOT/"docs/wise-route-manager-icon.svg").exists())
        self.assertIn("WISE_ENABLE_PROVIDER_MUTATIONS=0",installer)
        self.assertIn("ghcr.io/0o0-thedude-0o0/wise-unraid-route-manager:latest",installer)
        self.assertIn("docker rm -f",installer)
        self.assertIn("templates-user",installer)
        self.assertIn("my-wise-route-manager-lite.xml",installer)
        self.assertIn("<WebUI>http://[IP]:[PORT:9080]/</WebUI>",installer)
        entrypoint=(ROOT/"container/entrypoint.sh").read_text()
        self.assertIn('WISE_EDITION:-full',entrypoint)
        self.assertIn('starting web admin only on port 9080',entrypoint)
        self.assertIn('caddy_pid=',entrypoint)
        readme=(ROOT/"unraid-plugin/usr/local/emhttp/plugins/wise.route.manager/README.md").read_text()
        self.assertIn("<strong>Wise Route Manager</strong>",readme)
        self.assertNotIn("Thin Unraid integration",readme)
        self.assertNotIn("# ",readme)

    def test_release_assets_are_valid_and_parameterized(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(ROOT/"scripts"/"build-release-assets.sh"),"0.1.0-beta11","example","wise-route-manager",directory],cwd=ROOT,check=True,capture_output=True,text=True)
            output=Path(directory); plugin=ET.parse(output/"wise.route.manager.plg").getroot(); template=ET.parse(output/"wise-route-manager.xml").getroot(); lite=ET.parse(output/"wise-route-manager-lite.xml").getroot()
            self.assertEqual(plugin.attrib["version"],"0.1.0-beta11")
            self.assertIn("example/wise-route-manager",plugin.attrib["pluginURL"])
            self.assertIn("/releases/download/v0.1.0-beta11/wise.route.manager.plg",plugin.attrib["pluginURL"])
            self.assertTrue((output/"wise.route.manager-0.1.0_beta11-noarch-1.txz").exists())
            package_url=plugin.find("FILE/URL").text
            self.assertIn("wise.route.manager-0.1.0_beta11-noarch-1.txz",package_url)
            self.assertEqual(template.findtext("Repository"),"ghcr.io/example/wise-unraid-route-manager:latest")
            self.assertEqual(lite.findtext("Name"),"Wise Route Manager Lite")
            self.assertEqual(next(item for item in lite.findall("Config") if item.attrib.get("Target")=="WISE_EDITION").attrib.get("Default"),"lite")
            self.assertTrue((output/"SHA256SUMS").exists())


if __name__ == "__main__": unittest.main()
