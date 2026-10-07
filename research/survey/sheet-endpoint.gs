/**
 * fineprint 설문 응답 수집용 Google Apps Script
 *
 * survey/index.html 에서 보낸 응답을 Google 스프레드시트에 저장한다.
 * - responses 시트: 설문 답변 (익명)
 *
 * 설정 방법은 research/survey/README.md 참고.
 */
// 응답을 저장할 스프레드시트 ID (주소의 /d/ 와 /edit 사이)
const SHEET_ID = 'YOUR_SHEET_ID';

const FIELDS = [
  'loan_exp', 'products', 'read_level', 'skip_reasons', 'check_items',
  'surprised', 'surprised_story', 'summary_left', 'summary_question',
  'help_wanted', 'help_top', 'trust_needs', 'age', 'job', 'ua_mobile'
];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents || '{}');
    if (data._hp) return ok_();  // 스팸 봇이 채우는 숨은 필드

    const ss = SpreadsheetApp.openById(SHEET_ID);
    const now = new Date();

    const responses = sheet_(ss, 'responses', ['received_at'].concat(FIELDS));
    responses.appendRow([now].concat(FIELDS.map(function (k) { return clean_(data[k]); })));

    return ok_();
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  return ContentService.createTextOutput('fineprint survey endpoint is running.');
}

/** 배포 전에 한 번 실행해 권한을 승인하고 시트를 준비한다. */
function setup() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  ss.setSpreadsheetTimeZone('Asia/Seoul');
  sheet_(ss, 'responses', ['received_at'].concat(FIELDS));
}

function sheet_(ss, name, header) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.appendRow(header);
    sh.setFrozenRows(1);
  }
  return sh;
}

/** 문자열로 바꾸고 길이를 자르고, 수식으로 해석될 수 있는 값은 막는다. */
function clean_(v) {
  let s = v == null ? '' : String(v);
  s = s.slice(0, 2000);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function ok_() {
  return ContentService.createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
