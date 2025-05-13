"""
Main entry point for the UTAR Course Registration Scraper.
"""

import argparse
import os
import sys
import configparser
from src.gui.main_window import main

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='UTAR Course Registration Scraper')
    parser.add_argument('--timetable-file', type=str, help='Path to the timetable file')
    parser.add_argument('--method', type=str, choices=['beautifulsoup', 'selenium'], 
                        help='Scraping method to use (beautifulsoup or selenium)')
    parser.add_argument('--start', action='store_true',
                        help='Start the application immediately')
    return parser.parse_args()

if __name__ == '__main__':
    # Parse command line arguments
    args = parse_arguments()
    
    # Start the application
    main(args)