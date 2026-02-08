import yaml

from zone_setup import ZoneSetup
from main_security import SecuritySystem


def main():
    # load the config
    with open("configs/env_var.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    # Step 1: Run zone setup tool
    zone_setup = ZoneSetup(config)
    zone_setup.run_draw_zone()

    # Step 2: Start the security system
    security_system = SecuritySystem(config)
    security_system.run()


if __name__ == "__main__":
    main()