# tracker/views.py
from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.db import models
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, timedelta
import json
import csv
import io

# For Excel export
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

# For PDF export
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

from .models import Bill
class DashboardView(TemplateView):
    """Dashboard home page"""
    template_name = 'tracker/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get statistics
        context['total_bills'] = Bill.objects.count()
        context['pending_bills'] = Bill.objects.filter(status='PENDING').count()
        context['passed_bills'] = Bill.objects.filter(status='PASSED').count()
        context['rejected_bills'] = Bill.objects.filter(status='REJECTED').count()
        context['loksabha_bills'] = Bill.objects.filter(house='LOK_SABHA').count()
        context['rajyasabha_bills'] = Bill.objects.filter(house='RAJYA_SABHA').count()
        
        # Get recent bills - show a mix of Lok Sabha and Rajya Sabha
        recent_ls = Bill.objects.filter(house='LOK_SABHA').order_by('-introduction_date')[:5]
        recent_rs = Bill.objects.filter(house='RAJYA_SABHA').order_by('-introduction_date')[:5]
        
        # Combine and sort by date
        recent_bills = sorted(
            list(recent_ls) + list(recent_rs),
            key=lambda x: x.introduction_date or x.created_at,
            reverse=True
        )[:10]
        
        context['recent_bills'] = recent_bills
        
        return context

def bill_list(request):
    bills = Bill.objects.all().order_by('-introduction_date')

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        bills = bills.filter(
            models.Q(title__icontains=search_query) |
            models.Q(bill_id__icontains=search_query) |
            models.Q(bill_number__icontains=search_query) |
            models.Q(introduced_by__icontains=search_query)
        )

    # House filter
    house_param = request.GET.get('house', '')
    house_map = {
        'Lok Sabha': 'LOK_SABHA',
        'Rajya Sabha': 'RAJYA_SABHA',
        'Both': 'BOTH'
    }
    reverse_map = {v: k for k, v in house_map.items()}
    if house_param:
        db_house = house_map.get(house_param, house_param)
        bills = bills.filter(house=db_house)

    # Status filter
    status_param = request.GET.get('status', '')
    if status_param:
        bills = bills.filter(status=status_param.upper())

    # Pagination
    paginator = Paginator(bills, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Distinct houses for filter dropdown
    db_houses = set(Bill.objects.exclude(house__isnull=True).exclude(house='')
                    .values_list('house', flat=True).distinct())
    valid_houses = {'LOK_SABHA', 'RAJYA_SABHA', 'BOTH'}
    houses_to_show = [reverse_map.get(h, h.title().replace('_', ' '))
                      for h in db_houses if h in valid_houses]

    # Distinct statuses for filter dropdown
    db_statuses = set(Bill.objects.exclude(status__isnull=True).exclude(status='')
                      .values_list('status', flat=True).distinct())
    valid_statuses = {'PENDING', 'PASSED', 'REJECTED', 'WITHDRAWN', 'LAPSED'}
    statuses_to_show = [s for s in db_statuses if s in valid_statuses]

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'selected_house': house_param,
        'selected_status': status_param,
        'houses': houses_to_show,
        'statuses': statuses_to_show,
        'total_count': bills.count(),
    }
    return render(request, 'tracker/bill_list.html', context)


def bill_detail(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    return render(request, 'tracker/bill_detail.html', {'bill': bill})


def analytics(request):
    status_counts = list(Bill.objects.values('status').annotate(count=models.Count('status')))
    house_counts = list(Bill.objects.values('house').annotate(count=models.Count('house')))

    # Monthly trends (last 12 months)
    monthly_data = []
    for i in range(11, -1, -1):
        date = timezone.now().date() - timedelta(days=30*i)
        month_start = date.replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year+1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month+1, day=1) - timedelta(days=1)

        count = Bill.objects.filter(
            introduction_date__gte=month_start,
            introduction_date__lte=month_end
        ).count()
        monthly_data.append({'month': month_start.strftime('%b %Y'), 'count': count})

    context = {
        'status_counts': json.dumps(status_counts),
        'house_counts': json.dumps(house_counts),
        'monthly_data': json.dumps(monthly_data),
        'total_bills': Bill.objects.count(),
    }
    return render(request, 'tracker/analytics.html', context)


def map_view(request):
    """Map view with AJAX support"""
    status_filter = request.GET.get('status', 'all')
    year_filter = request.GET.get('year', 'all')

    bills = Bill.objects.all()
    if status_filter != 'all':
        bills = bills.filter(status=status_filter)
    if year_filter != 'all' and year_filter:
        bills = bills.filter(introduction_date__year=year_filter)

    # Simplified state mapping based on introducer/title
    minister_state_map = {
        'Minister of Finance': 'Maharashtra',
        'Minister of Home Affairs': 'Delhi',
        'Minister of Defence': 'Uttar Pradesh',
        'Minister of External Affairs': 'Delhi',
        'Minister of Law and Justice': 'West Bengal',
        'Minister of Electronics & IT': 'Karnataka',
        'Minister of Science and Technology': 'Tamil Nadu',
        'Minister of Ports and Shipping': 'Gujarat',
        'Minister of Labour and Employment': 'Bihar',
        'Minister of Health and Family Welfare': 'Madhya Pradesh',
        'Minister of Education': 'Rajasthan',
        'Minister of Agriculture': 'Punjab',
        'Minister of Railways': 'Odisha',
        'Minister of Coal': 'Jharkhand',
        'Minister of Petroleum': 'Assam',
        'Minister of Steel': 'Jharkhand',
        'Minister of Textiles': 'Gujarat',
        'Minister of Commerce': 'Tamil Nadu',
    }

    state_counts = {}
    for bill in bills:
        introducer = bill.introduced_by or ''
        state = 'Other'
        for minister, st in minister_state_map.items():
            if minister.lower() in introducer.lower():
                state = st
                break
        if state == 'Other' and bill.title:
            title_lower = bill.title.lower()
            if 'delhi' in title_lower:
                state = 'Delhi'
            elif 'maharashtra' in title_lower or 'mumbai' in title_lower:
                state = 'Maharashtra'
            elif 'tamil nadu' in title_lower or 'chennai' in title_lower:
                state = 'Tamil Nadu'
            elif 'west bengal' in title_lower or 'kolkata' in title_lower:
                state = 'West Bengal'
            elif 'karnataka' in title_lower or 'bangalore' in title_lower:
                state = 'Karnataka'
            elif 'telangana' in title_lower or 'hyderabad' in title_lower:
                state = 'Telangana'
            elif 'gujarat' in title_lower or 'ahmedabad' in title_lower:
                state = 'Gujarat'
        state_counts[state] = state_counts.get(state, 0) + 1

    states_data = [{'state': s, 'count': c} for s, c in state_counts.items()]

    # Distinct years for filter
    years = Bill.objects.exclude(introduction_date__isnull=True).dates('introduction_date', 'year')
    years_list = [y.year for y in years]

    # AJAX response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'states_data': states_data,
            'total_bills': bills.count(),
        })

    context = {
        'bills_data': json.dumps(states_data),
        'total_bills': bills.count(),
        'status_filter': status_filter,
        'year_filter': year_filter,
        'years': years_list,
    }
    return render(request, 'tracker/map.html', context)


def calendar_view(request):
    year = request.GET.get('year')
    month = request.GET.get('month')

    bills = Bill.objects.exclude(introduction_date__isnull=True)
    if year and month:
        bills = bills.filter(introduction_date__year=year, introduction_date__month=month)

    events = []
    for bill in bills:
        if bill.introduction_date:
            events.append({
                'title': f"{bill.bill_id}: {bill.title[:30]}",
                'start': bill.introduction_date.isoformat(),
                'url': f"/bills/{bill.id}/",
                'color': '#28a745' if bill.status == 'PASSED' else '#ffc107' if bill.status == 'PENDING' else '#dc3545'
            })

    context = {
        'events': json.dumps(events),
        'year': year,
        'month': month,
        'total_bills': Bill.objects.count(),
        'passed_count': Bill.objects.filter(status='PASSED').count(),
        'pending_count': Bill.objects.filter(status='PENDING').count(),
        'rejected_count': Bill.objects.filter(status='REJECTED').count() + Bill.objects.filter(status='WITHDRAWN').count(),
    }
    return render(request, 'tracker/calendar.html', context)


def api_bills(request):
    """API endpoint for bills"""
    bills = Bill.objects.all().order_by('-introduction_date')
    
    # Apply filters
    house = request.GET.get('house')
    if house and house != 'all':
        bills = bills.filter(house=house)
    
    status = request.GET.get('status')
    if status and status != 'all':
        bills = bills.filter(status=status)
    
    search = request.GET.get('search')
    if search:
        bills = bills.filter(
            models.Q(title__icontains=search) |
            models.Q(bill_id__icontains=search) |
            models.Q(bill_number__icontains=search)
        )
    
    date = request.GET.get('date')
    if date:
        bills = bills.filter(introduction_date=date)
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        bills = bills.filter(
            introduction_date__gte=start_date,
            introduction_date__lte=end_date
        )
    
    limit = int(request.GET.get('limit', 500))
    bills = bills[:limit]
    
    data = [{
        'id': str(bill.id),
        'bill_id': bill.bill_id,
        'bill_number': bill.bill_number or '',
        'title': bill.title,
        'house': bill.house,
        'status': bill.status,
        'introduction_date': bill.introduction_date.isoformat() if bill.introduction_date else None,
        'introduced_by': bill.introduced_by or '',
        'ministry': bill.ministry or '',
        'url': f"/bills/{bill.id}/"
    } for bill in bills]
    
    return JsonResponse({
        'bills': data,
        'count': len(data),
        'total': Bill.objects.count()
    })


def trigger_scrape(request):
    """Manual scrape trigger (uses scraper module)"""
    if request.method == 'POST':
        source = request.POST.get('source', 'all')
        try:
            from .scraper import RealBillScraper
            scraper = RealBillScraper()
            if source == 'all':
                result = scraper.scrape_all()
                message = "Scraping completed for all sources"
            elif source == 'MPA':
                result = scraper.scrape_mpa_bills()
                message = f"MPA scraping completed: {len(result)} bills"
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid source'})
            return JsonResponse({'status': 'success', 'message': message, 'result': result})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Scraping failed: {str(e)}'})

    # GET request – show form
    sources = [
        {'id': 'all', 'name': 'All Sources'},
        {'id': 'MPA', 'name': 'MPA (Ministry of Parliamentary Affairs)'},
    ]
    return render(request, 'tracker/scrape.html', {'sources': sources})


def export_bills(request):
    """Export bills in CSV, JSON, Excel, or PDF"""
    bills = Bill.objects.all().order_by('-introduction_date')
    data = []
    for bill in bills:
        data.append({
            'bill_id': bill.bill_id,
            'bill_number': bill.bill_number or '',
            'title': bill.title,
            'house': bill.get_house_display() if hasattr(bill, 'get_house_display') else bill.house,
            'status': bill.get_status_display() if hasattr(bill, 'get_status_display') else bill.status,
            'introduced_by': bill.introduced_by or '',
            'introduction_date': bill.introduction_date.strftime('%d %b %Y') if bill.introduction_date else '',
            'ministry': bill.ministry or '',
            'source': bill.source or '',
        })

    fmt = request.GET.get('format', 'csv')

    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="bills.csv"'
        if data:
            writer = csv.DictWriter(response, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return response

    elif fmt == 'json':
        return JsonResponse(data, safe=False)

    elif fmt == 'xlsx':
        wb = Workbook()
        ws = wb.active
        ws.title = "Bills"
        if data:
            headers = list(data[0].keys())
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header.replace('_', ' ').title())
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
            for row, bill in enumerate(data, 2):
                for col, key in enumerate(headers, 1):
                    ws.cell(row=row, column=col, value=bill[key])
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_len:
                            max_len = len(str(cell.value))
                    except:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 2, 50)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="bills.xlsx"'
        wb.save(response)
        return response

    elif fmt == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
        elements = []
        styles = getSampleStyleSheet()
        title = Paragraph("Bills Export", styles['Title'])
        elements.append(title)
        if data:
            headers = list(data[0].keys())
            table_data = [headers] + [[bill[h] for h in headers] for bill in data]
            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="bills.pdf"'
        response.write(pdf)
        return response

    else:
        return HttpResponse("Invalid format", status=400)
def analytics(request):
    """Analytics dashboard"""
    from django.db.models import Count, Q
    import json
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    # Get statistics for charts
    status_counts = list(Bill.objects.values('status').annotate(count=Count('status')))
    
    # Get house counts
    ls_count = Bill.objects.filter(house='LOK_SABHA').count()
    rs_count = Bill.objects.filter(house='RAJYA_SABHA').count()
    both_count = Bill.objects.filter(house='BOTH').count()
    
    house_counts = []
    if ls_count > 0:
        house_counts.append({'house': 'LOK_SABHA', 'count': ls_count})
    if rs_count > 0:
        house_counts.append({'house': 'RAJYA_SABHA', 'count': rs_count})
    if both_count > 0:
        house_counts.append({'house': 'BOTH', 'count': both_count})
    
    # Monthly trends (last 12 months)
    monthly_data = []
    today = timezone.now().date()
    
    for i in range(11, -1, -1):
        # Calculate month start and end
        month_date = today - timedelta(days=30*i)
        month_start = month_date.replace(day=1)
        
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year+1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month+1, day=1) - timedelta(days=1)
        
        # Get bills for this month
        month_bills = Bill.objects.filter(
            introduction_date__gte=month_start,
            introduction_date__lte=month_end
        )
        
        # Calculate counts
        total = month_bills.count()
        ls_month = month_bills.filter(house='LOK_SABHA').count()
        rs_month = month_bills.filter(house='RAJYA_SABHA').count()
        passed = month_bills.filter(status='PASSED').count()
        pending = month_bills.filter(status='PENDING').count()
        rejected = month_bills.filter(
            Q(status='REJECTED') | Q(status='WITHDRAWN') | Q(status='LAPSED')
        ).count()
        
        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'total': total,
            'ls_count': ls_month,
            'rs_count': rs_month,
            'passed': passed,
            'pending': pending,
            'rejected': rejected,
        })
    
    context = {
        'status_counts': json.dumps(status_counts),
        'house_counts': json.dumps(house_counts),
        'monthly_data': json.dumps(monthly_data),
        'total_bills': Bill.objects.count(),
        'ls_count': ls_count,
        'rs_count': rs_count,
        'both_count': both_count,
    }
    return render(request, 'tracker/analytics.html', context)