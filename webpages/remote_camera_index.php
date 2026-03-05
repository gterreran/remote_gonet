<?php
echo '<!DOCTYPE HTML>';
echo '<html>';
echo '<head>';
echo '<style>';
echo 'body';
echo '	{';
echo '		background:#000000;';
echo '		color:#ff5148;';
echo '		font-family:Arial, Helvetica, sans-serif;';
echo '		font-size:11px;';
echo '		font-weight:normal;';
echo '		margin:0px;';
echo '		padding:0px;';
echo '		overflow:hidden;';
echo '	}';
echo '</style>';
echo '</head>';
echo '<body>';

include('../nav/nav.php');

// define variables and set to empty values

if ($_SERVER["REQUEST_METHOD"] == "POST") {
	switch (test_input($_POST["action"])) {
		case "disable":
			exec('sudo crontab -u pi -r');
			exec('rm -rf /home/pi/Tools/Status/*; sudo -u pi touch /home/pi/Tools/Status/Disabled!');
			echo '<div style=margin-left:50px;>';
			echo '  <table width=550; style=color:#ff5148;>';
			echo '  <tbody>';
			echo '  <tr>';
			echo '  <td style=text-align:center><h3>Imaging disabled!</h3></td>';
			echo '  </tr>';
			echo '  </tbody>';
			echo '  </table>';
			echo '</div>';
			break;
		case "default":
			exec('sudo -u pi crontab /home/pi/Tools/Crontab/CronBackup.txt; rm -rf /home/pi/Tools/Crontab/status/*; sudo -u pi touch /home/pi/Tools/Crontab/status/Default; rm -rf /home/pi/Tools/Status/*; sudo -u pi touch /home/pi/Tools/Status/Ready');
			echo '<div style=margin-left:50px;>';
			echo '  <table width=550; style=color:#ff5148;>';
			echo '  <tbody>';
			echo '  <tr>';
			echo '  <td style=text-align:center><h3>Restored Default settings! <br><br>These settings will be applied during the next imaging cycle.</h3></td>';
			echo '  </tr>';
			echo '  </tbody>';
			echo '  </table>';
			echo '</div>';
			break;
		case "remote":
			exec('sudo -u pi crontab /home/pi/Tools/Crontab/CronRemoteBackup.txt; rm -rf /home/pi/Tools/Crontab/status/*; sudo -u pi touch /home/pi/Tools/Crontab/status/Remote; rm -rf /home/pi/Tools/Status/*; sudo -u pi touch /home/pi/Tools/Status/Ready');
			echo '<div style=margin-left:50px;>';
			echo '  <table width=550; style=color:#ff5148;>';
			echo '  <tbody>';
			echo '  <tr>';
			echo '  <td style=text-align:center><h3>Configured to use Remote settings! <br><br>These settings will be applied during the next imaging cycle.</h3></td>';
			echo '  </tr>';
			echo '  </tbody>';
			echo '  </table>';
			echo '</div>';
			break;
		case "terminate":
			exec('sudo pkill -f gonet4.py &');
			exec('rm -rf /home/pi/Tools/Status/*; sudo -u pi touch /home/pi/Tools/Status/Terminated!');
			echo '<div style=margin-left:50px;>';
			echo '  <table width=550; style=color:#ff5148;>';
			echo '  <tbody>';
			echo '  <tr>';
			echo '  <td style=text-align:center><h3>Imaging cycle terminated!</h3></td>';
			echo '  </tr>';
			echo '  </tbody>';
			echo '  </table>';
			echo '</div>';
			break;
		case "terminate_disable":
			exec('sudo crontab -u pi -r');
			exec('sudo pkill -f gonet4.py &');
			exec('rm -rf /home/pi/Tools/Status/*; sudo -u pi touch /home/pi/Tools/Status/TerminatedAndDisabled!');
			echo '<div style=margin-left:50px;>';
			echo '  <table width=550; style=color:#ff5148;>';
			echo '  <tbody>';
			echo '  <tr>';
			echo '  <td style=text-align:center><h3>Imaging disabled and terminated!</h3></td>';
			echo '  </tr>';
			echo '  </tbody>';
			echo '  </table>';
			echo '</div>';
			break;
	}
}

function test_input($data) {
  $data = trim($data);
  $data = stripslashes($data);
  $data = htmlspecialchars($data);
  return $data;
}

function test_key_input($data) {
  $data = trim($data);
  return $data;
}

echo '<div style=margin-left:50px;>';
echo "Current Imaging Mode: ";
echo `ls /home/pi/Tools/Crontab/status| sort -n | head -1`;
echo '<h2>Select new camera configuration</h2>';
echo '<form method="post" action="'.htmlspecialchars($_SERVER["PHP_SELF"]).'">';
echo '  <table width=550; style="color:#ff5148">';
echo '  <tbody>';
echo '  <tr>';
echo '  <td style="height:35px"><input type="radio" name="action" value="default"></td>';
echo '  <td style="height:35px">Default Settings</td>';
echo '  <td style="height:35px">GONet reverts to Default imaging settings after every reboot, taking 5 images with ISO of 800, and 6s exposure.</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td style="height:35px"><input type="radio" name="action" value="remote"></td>';
echo '  <td style="height:35px">Remote Settings</td>';
echo '  <td style="height:35px">GONet uses remote imaging settings, taking images based on remote configuration.</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td>&nbsp;</td>';
echo '  <td>&nbsp;</td>';
echo '  <td>&nbsp;</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td style="height:35px"><input type="radio" name="action" value="disable"></td>';
echo '  <td style="height:35px">Disable Imaging</td>';
echo '  <td style="height:35px">Disable automated imaging process.</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td style="height:35px"><input type="radio" name="action" value="terminate"></td>';
echo '  <td style="height:35px">Terminate Imaging</td>';
echo '  <td style="height:35px">Terminate current imaging cycle.</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td style="height:35px"><input type="radio" name="action" value="terminate_disable"></td>';
echo '  <td style="height:35px">Disable & Terminate Imaging</td>';
echo '  <td style="height:35px">Disable & Terminate automated imaging process.</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td>&nbsp;</td>';
echo '  <td>&nbsp;</td>';
echo '  <td>&nbsp;</td>';
echo '  </tr>';
echo '  <tr>';
echo '  <td colspan="3" align="center" style="height:35px"><input type="submit" name="submit" value="Submit"></td>';
echo '  </tr>';
echo '  </tbody>';
echo '  </table>';
echo '</form>';
echo '</div>';
echo '</body>';
echo '</html>';
?>