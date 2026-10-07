/**
 * fineprint 사용자 설문 - Google 폼 자동 생성 스크립트
 *
 * 사용법
 * 1. https://script.google.com 에서 [새 프로젝트]
 * 2. 기본 코드를 모두 지우고 이 파일 내용을 붙여 넣기
 * 3. 위쪽 함수 선택에서 createFineprintSurvey 를 고르고 [실행]
 * 4. 처음 한 번은 Google 권한 승인 창이 뜸 → 본인 계정으로 허용
 * 5. 아래 [실행 로그]에 나오는 "응답용 링크"를 사람들에게 공유
 */
function createFineprintSurvey() {
  var form = FormApp.create('금융 약관, 정말 읽고 동의하시나요? (5분 설문)');

  form.setDescription(
    '대출·카드·보험에 가입할 때 약관과 상품설명서를 어떻게 읽는지 알아보는 설문입니다.\n' +
    '금융 약관을 쉽게 이해하도록 돕는 개인 사이드 프로젝트(fineprint)를 위한 조사예요.\n\n' +
    '· 소요 시간: 약 5분\n' +
    '· 응답은 익명으로 처리되며, 통계와 익명 인용으로만 사용합니다.\n' +
    '· 이름, 계좌, 신용점수 같은 개인정보는 적지 말아 주세요.\n' +
    '· 이 설문은 특정 금융사와 관계가 없고, 금융상품을 권유하지 않습니다.'
  );
  form.setProgressBar(true);
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setConfirmationMessage('응답해 주셔서 감사합니다! 결과는 프로젝트 기록에 익명으로 정리해 공유할게요.');

  // ---------- 1. 경험 ----------
  form.addSectionHeaderItem().setTitle('1. 금융상품 이용 경험');

  form.addMultipleChoiceItem()
    .setTitle('최근 3년 안에 앱이나 웹으로 대출(신용대출, 카드론, 마이너스통장 등)을 받거나 알아본 적이 있나요?')
    .setChoiceValues(['받은 적 있다', '알아보기만 했다 (한도·금리 조회 등)', '없다'])
    .setRequired(true);

  form.addCheckboxItem()
    .setTitle('최근 3년 안에 앱으로 가입하거나 알아본 금융상품을 모두 골라 주세요.')
    .setChoiceValues(['신용대출', '카드론·현금서비스', '마이너스통장', '신용카드', '보험', '적금·예금', '해당 없음'])
    .showOtherOption(true);

  // ---------- 2. 약관 읽기 ----------
  form.addPageBreakItem().setTitle('2. 약관과 상품설명서 읽기');

  form.addScaleItem()
    .setTitle('동의 버튼을 누르기 전에 약관이나 상품설명서를 얼마나 읽나요?')
    .setBounds(1, 5)
    .setLabels('거의 안 읽는다', '꼼꼼히 다 읽는다')
    .setRequired(true);

  form.addCheckboxItem()
    .setTitle('약관을 끝까지 읽지 않는다면, 그 이유는 무엇인가요? (모두 선택)')
    .setChoiceValues([
      '너무 길다',
      '용어와 문장이 어렵다',
      '휴대폰 화면에서 글씨가 너무 작다',
      '어차피 동의해야 다음으로 넘어갈 수 있다',
      '중요한 내용은 앱 화면에 요약돼 있을 거라고 생각한다',
      '금융사를 믿는다',
      '시간이 없다',
      '끝까지 읽는 편이다'
    ])
    .showOtherOption(true);

  form.addCheckboxItem()
    .setTitle('대출이나 카드를 고를 때 직접 확인하는 조건을 모두 골라 주세요.')
    .setChoiceValues([
      '금리',
      '한도',
      '중도상환수수료',
      '금리가 바뀌는 조건 (변동금리, 변경 주기)',
      '연체했을 때의 이자와 불이익',
      '신용점수에 미치는 영향',
      '상환 방식 (원리금균등, 만기일시 등)',
      '부대 비용 (인지세, 보증료 등)',
      '거의 확인하지 않는다'
    ])
    .showOtherOption(true);

  // ---------- 3. 당황했던 경험 ----------
  form.addPageBreakItem().setTitle('3. 가입한 뒤에 알게 된 조건');

  form.addCheckboxItem()
    .setTitle('가입하거나 이용한 뒤에야 알게 돼서 당황했거나 손해를 본 조건이 있나요? (모두 선택)')
    .setChoiceValues([
      '중도상환수수료',
      '금리가 오르는 조건',
      '연체이자나 연체 시 불이익',
      '신용점수 하락',
      '자동 연장이나 만기 조건',
      '숨은 수수료나 부대 비용',
      '혜택 제외 조건 (카드 실적 등)',
      '보장 제외·면책 조건 (보험)',
      '그런 경험은 없다'
    ])
    .showOtherOption(true);

  form.addParagraphTextItem()
    .setTitle('그때 상황을 조금 더 알려 주실 수 있나요?')
    .setHelpText('예: "카드론을 일찍 갚으려 했는데 수수료가 있는 줄 몰랐다". 개인정보는 빼고 적어 주세요. (선택)');

  // ---------- 4. 요약 화면 ----------
  form.addPageBreakItem().setTitle('4. 앱의 요약 화면');

  form.addMultipleChoiceItem()
    .setTitle('일부 앱은 대출 신청 전에 핵심 내용을 카드나 요약 화면으로 보여 줍니다. 그 요약을 본 뒤에도 궁금한 점이 남았던 적이 있나요?')
    .setChoiceValues(['있다', '없다, 요약으로 충분했다', '요약 화면을 본 기억이 없다'])
    .setRequired(true);

  form.addParagraphTextItem()
    .setTitle('요약을 보고도 남았던 궁금증은 무엇이었나요?')
    .setHelpText('예: "3년 안에 갚으면 정확히 얼마를 내야 하는지", "한 번 연체하면 어떻게 되는지" (선택)');

  // ---------- 5. 필요한 도움 ----------
  form.addPageBreakItem().setTitle('5. 어떤 도움이 있으면 좋을까요');

  var helpOptions = [
    '내 상황을 물어보면 약관에서 해당 조항을 찾아 근거와 함께 답해 주기',
    '여러 금융사의 같은 조건을 나란히 비교해 주기',
    '꼭 알아야 할 핵심 조건만 짧게 요약해 주기',
    '동의하기 전에 내가 핵심 조건을 제대로 이해했는지 확인해 주기',
    '사람 상담원에게 바로 물어볼 수 있게 연결해 주기'
  ];

  form.addCheckboxItem()
    .setTitle('약관을 이해하는 데 어떤 도움이 있으면 좋겠나요? (모두 선택)')
    .setChoiceValues(helpOptions.concat(['딱히 필요 없다']))
    .showOtherOption(true);

  form.addMultipleChoiceItem()
    .setTitle('그중 하나만 고른다면 무엇인가요?')
    .setChoiceValues(helpOptions)
    .showOtherOption(true)
    .setRequired(true);

  form.addCheckboxItem()
    .setTitle('AI가 약관을 설명해 준다면, 그 답을 믿으려면 무엇이 필요할까요? (모두 선택)')
    .setChoiceValues([
      '약관 원문의 조항 번호와 문장을 함께 보여 주기',
      '모르는 건 모른다고 말하기',
      '금융사나 공식 기관이 확인한 정보라는 표시',
      '틀렸을 때 사람에게 다시 확인할 방법',
      'AI 설명은 믿기 어렵다'
    ])
    .showOtherOption(true);

  // ---------- 6. 응답자 정보 ----------
  form.addPageBreakItem().setTitle('6. 응답자 정보 (통계용)');

  form.addMultipleChoiceItem()
    .setTitle('연령대')
    .setChoiceValues(['20대', '30대', '40대', '50대 이상', '응답하지 않음']);

  form.addMultipleChoiceItem()
    .setTitle('하시는 일')
    .setChoiceValues(['직장인', '자영업·프리랜서', '학생', '금융업 종사자', '그 외', '응답하지 않음']);

  // ---------- 7. 인터뷰 ----------
  form.addPageBreakItem()
    .setTitle('7. 인터뷰 참여 (선택)')
    .setHelpText('20~30분 정도 온라인으로 조금 더 이야기를 나눠 주실 분을 찾고 있어요.');

  form.addMultipleChoiceItem()
    .setTitle('짧은 인터뷰에 참여해 주실 수 있나요?')
    .setChoiceValues(['네, 참여할게요', '아니요']);

  form.addTextItem()
    .setTitle('참여해 주신다면 연락받을 방법을 적어 주세요. (이메일 또는 카카오톡 ID)')
    .setHelpText(
      '[개인정보 수집·이용 안내] 수집 항목: 이메일 또는 카카오톡 ID / ' +
      '목적: 인터뷰 일정 연락 / 보관 기간: 인터뷰 종료 후 즉시 파기 / ' +
      '동의하지 않으셔도 설문 참여에는 불이익이 없습니다. 적어 주시면 위 내용에 동의한 것으로 봅니다.'
    );

  Logger.log('응답용 링크 (공유하세요): ' + form.getPublishedUrl());
  Logger.log('수정용 링크 (본인만): ' + form.getEditUrl());
}
