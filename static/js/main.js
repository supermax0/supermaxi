/**
 * الملف الرئيسي لجافاسكريبت لنظام المحاسبة
 */

$(document).ready(function() {
    // تهيئة مكونات Bootstrap
    initBootstrapComponents();
    
    // تهيئة DataTables
    initDataTables();
    
    // إدارة الإشعارات
    initNotifications();
    
    // التحقق من النماذب
    initFormValidation();
});

/**
 * تهيئة مكونات Bootstrap
 */
function initBootstrapComponents() {
    // تفعيل جميع عناصر الـ tooltip
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl, {
            placement: 'top',
            trigger: 'hover'
        });
    });
    
    // تفعيل جميع عناصر الـ popover
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
}

/**
 * تهيئة DataTables
 */
function initDataTables() {
    if ($.fn.DataTable) {
        $('table.datatable').DataTable({
            language: {
                url: '//cdn.datatables.net/plug-ins/1.11.5/i18n/ar.json'
            },
            pageLength: 25,
            responsive: true,
            order: [],
            columnDefs: [
                { orderable: false, targets: 'no-sort' }
            ]
        });
    }
}

/**
 * إدارة الإشعارات
 */
function initNotifications() {
    // إخفاء الإشعارات تلقائياً بعد 5 ثواني
    $('.alert').not('.alert-permanent').delay(5000).fadeTo(500, 0).slideUp(500, function() {
        $(this).remove();
    });
    
    // زر إغلاق الإشعارات
    $('.alert .btn-close').on('click', function() {
        $(this).closest('.alert').remove();
    });
}

/**
 * التحقق من النماذج
 */
function initFormValidation() {
    // التحقق من الأرقام فقط
    $('.numbers-only').on('input', function() {
        this.value = this.value.replace(/[^0-9]/g, '');
    });
    
    // التحقق من الأرقام العشرية
    $('.decimal-only').on('input', function() {
        this.value = this.value.replace(/[^0-9.]/g, '');
    });
    
    // التحقق من البريد الإلكتروني
    $('.email-validation').on('blur', function() {
        const email = $(this).val();
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        
        if (email && !emailRegex.test(email)) {
            $(this).addClass('is-invalid');
            $(this).after('<div class="invalid-feedback">البريد الإلكتروني غير صالح</div>');
        } else {
            $(this).removeClass('is-invalid');
            $(this).next('.invalid-feedback').remove();
        }
    });
    
    // التحقق من أن الحقل مطلوب
    $('form').on('submit', function() {
        let valid = true;
        
        $(this).find('[required]').each(function() {
            if (!$(this).val().trim()) {
                valid = false;
                $(this).addClass('is-invalid');
                
                if (!$(this).next('.invalid-feedback').length) {
                    $(this).after('<div class="invalid-feedback">هذا الحقل مطلوب</div>');
                }
            } else {
                $(this).removeClass('is-invalid');
                $(this).next('.invalid-feedback').remove();
            }
        });
        
        return valid;
    });
}

/**
 * تحميل المحتوى عبر AJAX
 */
function loadContent(url, container, callback) {
    $(container).html(`
        <div class="text-center py-4">
            <div class="spinner-border text-primary"></div>
            <p class="mt-2">جاري التحميل...</p>
        </div>
    `);
    
    $.ajax({
        url: url,
        method: 'GET',
        success: function(data) {
            $(container).html(data);
            if (callback) callback();
        },
        error: function() {
            $(container).html(`
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i>
                    حدث خطأ أثناء تحميل المحتوى. يرجى المحاولة مرة أخرى.
                </div>
            `);
        }
    });
}

/**
 * تحديث عداد الأحرف
 */
function initCharCounter() {
    $('.char-counter').each(function() {
        const maxLength = $(this).data('maxlength') || 255;
        const counterId = 'counter-' + $(this).attr('id');
        
        $(this).after(`
            <div class="form-text text-end">
                <span id="${counterId}">0</span> / ${maxLength}
            </div>
        `);
        
        $(this).on('input', function() {
            const length = $(this).val().length;
            const counter = $('#' + counterId);
            
            counter.text(length);
            
            if (length > maxLength) {
                counter.addClass('text-danger');
                $(this).val($(this).val().substring(0, maxLength));
            } else {
                counter.removeClass('text-danger');
            }
        }).trigger('input');
    });
}

/**
 * نسخ النص إلى الحافظة
 */
function copyToClipboard(text, successMessage) {
    navigator.clipboard.writeText(text).then(function() {
        showToast(successMessage || 'تم النسخ إلى الحافظة', 'success');
    }, function() {
        showToast('فشل النسخ إلى الحافظة', 'error');
    });
}

/**
 * عرض رسالة toast
 */
function showToast(message, type) {
    const toastId = 'toast-' + Date.now();
    const toastHtml = `
        <div class="toast align-items-center text-white bg-${type} border-0" id="${toastId}" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    $('.toast-container').append(toastHtml);
    const toastElement = $('#' + toastId);
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
    
    toastElement.on('hidden.bs.toast', function() {
        $(this).remove();
    });
}

/**
 * تنسيق الأرقام
 */
function formatNumber(number, decimals = 2) {
    return parseFloat(number).toLocaleString('ar-SA', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * تنسيق التاريخ
 */
function formatDate(dateString, format = 'YYYY-MM-DD') {
    const date = new Date(dateString);
    
    if (isNaN(date.getTime())) {
        return dateString;
    }
    
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    
    switch (format) {
        case 'YYYY-MM-DD':
            return `${year}-${month}-${day}`;
        case 'DD/MM/YYYY':
            return `${day}/${month}/${year}`;
        case 'MM/DD/YYYY':
            return `${month}/${day}/${year}`;
        default:
            return date.toLocaleDateString('ar-SA');
    }
}

/**
 * التحقق من صحة الصورة قبل رفعها
 */
function validateImage(file, maxSizeMB = 5) {
    const maxSize = maxSizeMB * 1024 * 1024; // تحويل إلى بايت
    
    if (!file.type.match('image.*')) {
        return 'الملف يجب أن يكون صورة';
    }
    
    if (file.size > maxSize) {
        return `حجم الصورة يجب أن يكون أقل من ${maxSizeMB}MB`;
    }
    
    return null;
}

/**
 * إنشاء رمز QR
 */
function generateQRCode(elementId, text) {
    if (typeof QRCode !== 'undefined') {
        new QRCode(document.getElementById(elementId), {
            text: text,
            width: 128,
            height: 128,
            colorDark: "#000000",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.H
        });
    }
}

// جعل الدوال متاحة عالمياً
window.AccountingSystem = {
    loadContent,
    copyToClipboard,
    showToast,
    formatNumber,
    formatDate,
    validateImage,
    generateQRCode,
    initCharCounter
};