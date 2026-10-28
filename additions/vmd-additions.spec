Name:           vmd-additions
Version:        1
Release:        6
Summary:        Microphone and cameras from Minecraft (Virtual Machine Desktops)
License:        MIT
BuildArch:      noarch
Requires:       python3, pipewire-utils, systemd
Source0:        vmd-agent.py
Source1:        vmd-agent.service
Source2:        vmd-additions-setup.sh
Source3:        vmd-additions-setup.service
Source4:        60-vmd-additions.rules
Source5:        vmd-v4l2loopback.conf
Source6:        vmd-modules-load.conf

%description
Lets this Linux, running inside the Minecraft mod Virtual Machine Desktops, use a microphone and two cameras the mod provides: your voice mixed with Minecraft's sounds, your real webcam, and a camera filming the Minecraft world.

After installing, the camera driver (v4l2loopback from RPM Fusion) is set up in the background.

%install
install -Dm755 %{SOURCE0} %{buildroot}/usr/libexec/vmd-additions/vmd-agent
install -Dm644 %{SOURCE1} %{buildroot}/usr/lib/systemd/user/vmd-agent.service
install -Dm755 %{SOURCE2} %{buildroot}/usr/libexec/vmd-additions/vmd-additions-setup
install -Dm644 %{SOURCE3} %{buildroot}/usr/lib/systemd/system/vmd-additions-setup.service
install -Dm644 %{SOURCE4} %{buildroot}/usr/lib/udev/rules.d/60-vmd-additions.rules
install -Dm644 %{SOURCE5} %{buildroot}/usr/lib/modprobe.d/vmd-v4l2loopback.conf
install -Dm644 %{SOURCE6} %{buildroot}/usr/lib/modules-load.d/vmd-v4l2loopback.conf

%post
udevadm control --reload-rules >/dev/null 2>&1 || :
udevadm trigger --subsystem-match=virtio-ports >/dev/null 2>&1 || :
systemctl --global enable vmd-agent.service >/dev/null 2>&1 || :
systemctl enable vmd-additions-setup.service >/dev/null 2>&1 || :
systemctl start --no-block vmd-additions-setup.service >/dev/null 2>&1 || :
# start the agent in every open session now, not only after the next login
for uid in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $1}'); do
	systemctl --user -M "$uid@" start vmd-agent.service >/dev/null 2>&1 || :
done

%preun
if [ "$1" = 0 ]; then
	systemctl --global disable vmd-agent.service >/dev/null 2>&1 || :
	systemctl disable vmd-additions-setup.service >/dev/null 2>&1 || :
fi

%files
/usr/libexec/vmd-additions/vmd-agent
/usr/libexec/vmd-additions/vmd-additions-setup
/usr/lib/systemd/user/vmd-agent.service
/usr/lib/systemd/system/vmd-additions-setup.service
/usr/lib/udev/rules.d/60-vmd-additions.rules
/usr/lib/modprobe.d/vmd-v4l2loopback.conf
/usr/lib/modules-load.d/vmd-v4l2loopback.conf
