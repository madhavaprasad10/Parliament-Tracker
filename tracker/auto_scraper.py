# tracker/auto_scraper.py
import threading
import time
import logging
from datetime import datetime
from django.db import models  # ADD THIS IMPORT

logger = logging.getLogger(__name__)

class AutoScraper:
    _instance = None
    _thread = None
    _running = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Auto-scraper started in background")
    
    def stop(self):
        self._running = False
        logger.info("Auto-scraper stopped")
    
    def _run(self):
        time.sleep(5)
        from .scraper import RealBillScraper
        scraper = RealBillScraper()
        
        while self._running:
            try:
                logger.info("Auto-scraping new bills...")
                scrape_results = scraper.scrape_all()
                logger.info(f"New bills scrape: {scrape_results}")
                
                # Count bills missing details
                from .models import Bill
                missing_details = Bill.objects.filter(
                    models.Q(bill_number='') | 
                    models.Q(bill_number__isnull=True) |
                    models.Q(introduced_by='') | 
                    models.Q(introduced_by__isnull=True) |
                    models.Q(introduced_by='Minister Concerned')
                ).count()
                
                if missing_details > 0:
                    logger.info(f"Found {missing_details} bills missing details. Updating...")
                    # We'll need to add this method to scraper
                    if hasattr(scraper, 'update_all_bill_details'):
                        detail_results = scraper.update_all_bill_details(limit=50)
                        logger.info(f"Detail update results: {detail_results}")
                    else:
                        logger.warning("update_all_bill_details method not found in scraper")
                
                # Wait 1 hour before next scrape
                for _ in range(60):
                    if not self._running:
                        break
                    time.sleep(60)
                    
            except Exception as e:
                logger.error(f"Auto-scrape error: {e}")
                time.sleep(60)

auto_scraper = AutoScraper()