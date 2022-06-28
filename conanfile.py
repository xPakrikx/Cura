import os
import sys
from pathlib import Path

from io import StringIO

from platform import python_version

from jinja2 import Template

from conan import ConanFile
from conan.tools import files
from conan.tools.env import VirtualRunEnv
from conans import tools
from conan.errors import ConanInvalidConfiguration, ConanException

required_conan_version = ">=1.47.0"


class CuraConan(ConanFile):
    name = "cura"
    license = "LGPL-3.0"
    author = "Ultimaker B.V."
    url = "https://github.com/Ultimaker/cura"
    description = "3D printer / slicing GUI built on top of the Uranium framework"
    topics = ("conan", "python", "pyqt5", "qt", "qml", "3d-printing", "slicer")
    build_policy = "missing"
    exports = "LICENSE*", "Ultimaker-Cura.spec.jinja", "CuraVersion.py.jinja"
    settings = "os", "compiler", "build_type", "arch"
    no_copy_source = True  # We won't build so no need to copy sources to the build folder

    # FIXME: Remove specific branch once merged to main
    # Extending the conanfile with the UMBaseConanfile https://github.com/Ultimaker/conan-ultimaker-index/tree/CURA-9177_Fix_CI_CD/recipes/umbase
    python_requires = "umbase/0.1.2@ultimaker/testing"
    python_requires_extend = "umbase.UMBaseConanfile"

    options = {
        "enterprise": ["True", "False", "true", "false"],  # Workaround for GH Action passing boolean as lowercase string
        "staging": ["True", "False", "true", "false"],  # Workaround for GH Action passing boolean as lowercase string
        "devtools": [True, False],  # FIXME: Split this up in testing and (development / build (pyinstaller) / system installer) tools
        "cloud_api_version": "ANY",
        "display_name": "ANY",  # TODO: should this be an option??
        "cura_debug_mode": [True, False]  # FIXME: Use profiles
    }
    default_options = {
        "enterprise": "False",
        "staging": "False",
        "devtools": False,
        "cloud_api_version": "1",
        "display_name": "Ultimaker Cura",
        "cura_debug_mode": False
    }
    scm = {
        "type": "git",
        "subfolder": ".",
        "url": "auto",
        "revision": "auto"
    }

    @property
    def _staging(self):
        return self.options.staging in ["True", 'true']

    @property
    def _enterprise(self):
        return self.options.enterprise in ["True", 'true']

    @property
    def _cloud_api_root(self):
        return "https://api-staging.ultimaker.com" if self._staging else "https://api.ultimaker.com"

    @property
    def _cloud_account_api_root(self):
        return "https://account-staging.ultimaker.com" if self._staging else "https://account.ultimaker.com"

    @property
    def _marketplace_root(self):
        return "https://marketplace-staging.ultimaker.com" if self._staging else "https://marketplace.ultimaker.com"

    @property
    def _digital_factory_url(self):
        return "https://digitalfactory-staging.ultimaker.com" if self._staging else "https://digitalfactory.ultimaker.com"

    @property
    def requirements_txts(self):
        if self.options.devtools:
            return ["requirements.txt", "requirements-ultimaker.txt", "requirements-dev.txt"]
        return ["requirements.txt", "requirements-ultimaker.txt"]

    def source(self):
        with open(Path(self.source_folder, "CuraVersion.py.jinja"), "r") as f:
            cura_version_py = Template(f.read())

        with open(Path(self.source_folder, "cura", "CuraVersion.py"), "w") as f:
            f.write(cura_version_py.render(
                cura_app_name = self.name,
                cura_app_display_name = self.options.display_name,
                cura_version = self.version,
                cura_build_type = "Enterprise" if self._enterprise else "",
                cura_debug_mode = self.options.cura_debug_mode,
                cura_cloud_api_root = self._cloud_api_root,
                cura_cloud_api_version = self.options.cloud_api_version,
                cura_cloud_account_api_root = self._cloud_account_api_root,
                cura_marketplace_root = self._marketplace_root,
                cura_digital_factory_url = self._digital_factory_url))

    def configure(self):
        self.options["arcus"].shared = True
        self.options["savitar"].shared = True
        self.options["pynest2d"].shared = True
        self.options["cpython"].shared = True

    def validate(self):
        if self.version and tools.Version(self.version) <= tools.Version("4"):
            raise ConanInvalidConfiguration("Only versions 5+ are support")

    def requirements(self):
        for req in self._um_data(self.version)["requirements"]:
            self.requires(req)

    def layout(self):
        self.folders.source = "."
        self.folders.build = "venv"
        self.folders.generators = os.path.join(self.folders.build, "conan")

        self.cpp.package.libdirs = ["site-packages"]
        self.cpp.package.resdirs = ["res", "pip_requirements"]  # Note: pip_requirements should be the last item in the list

    def generate(self):
        if self.options.devtools:
            with open(Path(self.source_folder, "Ultimaker-Cura.spec.jinja"), "r") as f:
                pyinstaller = Template(f.read())

            pyinstaller_metadata = self._um_data(self.version)["pyinstaller"]
            datas = []
            for data in pyinstaller_metadata["datas"].values():
                if "package" in data:  # get the paths from conan package
                    if data["package"] == self.name:
                        src_path = Path(self.package_folder, data["src"])
                    else:
                        src_path = Path(self.deps_cpp_info[data["package"]].rootpath, data["src"])
                elif "root" in data:  # get the paths relative from the sourcefolder
                    src_path = Path(self.source_folder, data["root"], data["src"])
                else:
                    continue
                if src_path.exists():
                    datas.append((str(src_path), data["dst"]))

            binaries = []
            for binary in pyinstaller_metadata["binaries"].values():
                if "package" in binary:  # get the paths from conan package
                    src_path = Path(self.deps_cpp_info[binary["package"]].rootpath, binary["src"])
                elif "root" in binary:  # get the paths relative from the sourcefolder
                    src_path = Path(self.source_folder, binary["root"], binary["src"])
                else:
                    continue
                if not src_path.exists():
                    continue
                for bin in src_path.glob(binary["binary"] + ".*[exe|dll|so|dylib]"):
                    binaries.append((str(bin), binary["dst"]))
                for bin in src_path.glob(binary["binary"]):
                    binaries.append((str(bin), binary["dst"]))

            with open(Path(self.generators_folder, "Ultimaker-Cura.spec"), "w") as f:
                f.write(pyinstaller.render(
                    name = str(self.options.display_name).replace(" ", "-"),
                    entrypoint = os.path.join("..", "..", self._um_data(self.version)["runinfo"]["entrypoint"]),
                    datas = datas,
                    binaries = binaries,
                    hiddenimports = pyinstaller_metadata["hiddenimports"],
                    collect_all = pyinstaller_metadata["collect_all"],
                    icon = os.path.join("..", "..", pyinstaller_metadata["icon"][str(self.settings.os)])
                ))

    def imports(self):
        self.copy("CuraEngine.exe", root_package = "curaengine", src = "@bindirs", dst = "", keep_path = False)
        self.copy("CuraEngine", root_package = "curaengine", src = "@bindirs", dst = "", keep_path = False)

        files.rmdir(self, "resources/materials")
        self.copy("*.fdm_material", root_package = "fdm_materials", src = "@resdirs", dst = "resources/materials", keep_path = False)
        self.copy("*.sig", root_package = "fdm_materials", src = "@resdirs", dst = "resources/materials", keep_path = False)

        self.copy("*.dll", src = "@bindirs", dst = "venv/Lib/site-packages")
        self.copy("*.pyd", src = "@libdirs", dst = "venv/Lib/site-packages")
        self.copy("*.pyi", src = "@libdirs", dst = "venv/Lib/site-packages")
        self.copy("*.dylib", src = "@libdirs", dst = "venv/bin")

    def deploy(self):
        # Setup the Virtual Python Environment in the user space
        self._generate_virtual_python_env("wheel", "setuptools")

        # TODO: Maybe we should create one big requirement.txt at this stage looping over the individual requirements from this conanfile
        #  and the dependencies, has less fine-grained results. If there is a duplicate dependency is installed over the previous installed version

        # Install the requirements*.txt for Cura her dependencies
        # Note: can't you lists in user_info, that why it's split up
        for dep_name in self.deps_user_info:
            dep_user_info = self.deps_user_info[dep_name]
            pip_req_paths = [req_path for req_path in self.deps_cpp_info[dep_name].resdirs if req_path == "pip_requirements"]
            if len(pip_req_paths) != 1:
                continue
            pip_req_base_path = Path(pip_req_paths[0])
            if hasattr(dep_user_info, "pip_requirements"):
                req_txt = pip_req_base_path.joinpath(dep_user_info.pip_requirements)
                if req_txt.exists():
                    self.run(f"{self._py_venv_interp} -m pip install -r {req_txt}", run_environment = True, env = "conanrun")
                    self.output.success(f"Dependency {dep_name} specifies pip_requirements in user_info installed!")
                else:
                    self.output.warn(f"Dependency {dep_name} specifies pip_requirements in user_info but {req_txt} can't be found!")

            if hasattr(dep_user_info, "pip_requirements_git"):
                req_txt = pip_req_base_path.joinpath(dep_user_info.pip_requirements_git)
                if req_txt.exists():
                    self.run(f"{self._py_venv_interp} -m pip install -r {req_txt}", run_environment = True, env = "conanrun")
                    self.output.success(f"Dependency {dep_name} specifies pip_requirements_git in user_info installed!")
                else:
                    self.output.warn(f"Dependency {dep_name} specifies pip_requirements_git in user_info but {req_txt} can't be found!")

        # Install Cura requirements*.txt
        pip_req_base_path = Path(self.cpp_info.rootpath, self.cpp_info.resdirs[-1])
        # Add the dev reqs needed for pyinstaller
        self.run(f"{self._py_venv_interp} -m pip install -r {pip_req_base_path.joinpath(self.user_info.pip_requirements_build)}",
                 run_environment = True, env = "conanrun")

        # Install the requirements.text for cura
        self.run(f"{self._py_venv_interp} -m pip install -r {pip_req_base_path.joinpath(self.user_info.pip_requirements_git)}",
                 run_environment = True, env = "conanrun")
        # Do the final requirements last such that these dependencies takes precedence over possible previous installed Python modules.
        # Since these are actually shipped with Cura and therefore require hashes and pinned version numbers in the requirements.txt
        self.run(f"{self._py_venv_interp} -m pip install -r {pip_req_base_path.joinpath(self.user_info.pip_requirements)}",
                 run_environment = True, env = "conanrun")

        # Copy CuraEngine.exe to bindirs of Virtual Python Environment
        # TODO: Fix source such that it will get the curaengine relative from the executable (Python bindir in this case)
        self.copy_deps("CuraEngine.exe", root_package = "curaengine", src = "@bindirs",
                       dst = os.path.join(self.install_folder, self._python_venv_bin_path), keep_path = False)
        self.copy_deps("CuraEngine", root_package = "curaengine", src = "@bindirs",
                       dst = os.path.join(self.install_folder, self._python_venv_bin_path), keep_path = False)

        # Copy resources of Cura (keep folder structure)
        self.copy_deps("*", root_package = "cura", src = "@resdirs", dst = os.path.join(self.install_folder, "share", "cura", "resources"),
                       keep_path = True)

        # Copy materials (flat)
        self.copy_deps("*.fdm_material", root_package = "fdm_materials", src = "@resdirs",
                       dst = os.path.join(self.install_folder, "share", "cura", "resources", "materials"), keep_path = False)
        self.copy_deps("*.sig", root_package = "fdm_materials", src = "@resdirs",
                       dst = os.path.join(self.install_folder, "share", "cura", "resources", "materials"), keep_path = False)

        # Copy resources of Uranium (keep folder structure)
        self.copy_deps("*", root_package = "uranium", src = "@resdirs",
                       dst = os.path.join(self.install_folder, "share", "cura", "resources"), keep_path = True)

        # Copy dynamic libs to site-packages
        self.copy_deps("*.dll", src = "@bindirs", dst = "venv/Lib/site-packages")
        self.copy_deps("*.pyd", src = "@libdirs", dst = "venv/Lib/site-packages")
        self.copy_deps("*.pyi", src = "@libdirs", dst = "venv/Lib/site-packages")
        self.copy_deps("*.dylib", src = "@libdirs", dst = "venv/bin")

        # Make sure the CuraVersion.py is up to date with the correct settings
        with open(Path(Path(__file__).parent, "CuraVersion.py.jinja"), "r") as f:
            cura_version_py = Template(f.read())

        # TODO: Extend

    def package(self):
        self.copy("*", src = "cura", dst = os.path.join(self.cpp.package.libdirs[0], "cura"))
        self.copy("*", src = "plugins", dst = os.path.join(self.cpp.package.libdirs[0], "plugins"))
        self.copy("*", src = "resources", dst = os.path.join(self.cpp.package.resdirs[0], "resources"))
        self.copy("requirement*.txt", src = ".", dst = self.cpp.package.resdirs[1])

    def package_info(self):
        self.user_info.pip_requirements = "requirements.txt"
        self.user_info.pip_requirements_git = "requirements-ultimaker.txt"
        self.user_info.pip_requirements_build = "requirements-dev.txt"
        if self.in_local_cache:
            self.runenv_info.append_path("PYTHONPATH", self.cpp_info.libdirs[0])
        else:
            self.runenv_info.append_path("PYTHONPATH", self.source_folder)

    def package_id(self):
        del self.info.settings.os
        del self.info.settings.compiler
        del self.info.settings.build_type
        del self.info.settings.arch

        # The following options shouldn't be used to determine the hash, since these are only used to set the CuraVersion.py
        # which will als be generated by the deploy method during the `conan install cura/5.1.0@_/_`
        del self.info.options.enterprise
        del self.info.options.staging
        del self.info.options.devtools
        del self.info.options.cloud_api_version
        del self.info.options.display_name
        del self.info.options.cura_debug_mode

        # TODO: Use the hash of requirements.txt and requirements-ultimaker.txt, Because changing these will actually result in a different
        #  Cura. This is needed because the requirements.txt aren't managed by Conan and therefor not resolved in the package_id. This isn't
        #  ideal but an acceptable solution for now.
