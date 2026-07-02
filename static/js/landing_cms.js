(function () {
  'use strict';

  function videoEmbed(url) {
    if (!url) return '';
    if (/youtube\.com|youtu\.be/.test(url)) {
      var id = url.split('v=')[1] || url.split('/').pop();
      id = (id || '').split('&')[0].split('?')[0];
      return '<iframe src="https://www.youtube.com/embed/' + id + '" allowfullscreen loading="lazy"></iframe>';
    }
    if (/vimeo\.com/.test(url)) {
      var vid = url.split('/').pop();
      return '<iframe src="https://player.vimeo.com/video/' + vid + '" allowfullscreen loading="lazy"></iframe>';
    }
    return '<video controls preload="metadata" src="' + url.replace(/"/g, '&quot;') + '"></video>';
  }

  var modal = document.getElementById('videoModal');
  var host = document.getElementById('videoHost');
  var close = document.getElementById('videoClose');
  document.querySelectorAll('[data-video-open]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      host.innerHTML = videoEmbed(btn.getAttribute('data-video-url'));
      modal.hidden = false;
    });
  });
  if (close) {
    close.addEventListener('click', function () {
      modal.hidden = true;
      host.innerHTML = '';
    });
  }
})();
