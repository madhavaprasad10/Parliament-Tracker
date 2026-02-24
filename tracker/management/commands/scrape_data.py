from django.core.management.base import BaseCommand
from tracker.scraper import ParliamentScraper
class Command(BaseCommand):
    help = 'Scrape parliamentary data'
    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, default='prs')
    def handle(self, *args, **options):
        scraper = ParliamentScraper()
        source = options['source']
        if source == 'prs':
            data = scraper.scrape_prs_bills()
        else:
            data = []
        scraper.save_to_database({'prs_data':data})
        self.stdout.write(self.style.SUCCESS(f"Scraped {len(data)} records"))