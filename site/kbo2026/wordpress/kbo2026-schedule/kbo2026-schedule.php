<?php
/**
 * Plugin Name: 2026 프로야구 일정 중계
 * Description: KBO 공식 일정을 자동으로 받아 남은 경기와 날짜별 중계 채널을 보여 줍니다. 숏코드: [kbo_next] [kbo_schedule] [kbo_day] [kbo_channels] [kbo_channel_codes]
 * Version: 1.0.0
 * Requires at least: 6.0
 * Requires PHP: 7.4
 * License: MIT
 * Text Domain: kbo2026-schedule
 */

defined( 'ABSPATH' ) || exit;

define( 'KBO26_VER', '1.0.0' );
define( 'KBO26_FILE', __FILE__ );
define( 'KBO26_URL', 'https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList' );

/* KBO 일정 API 의 경기 구분 코드 */
function kbo26_series() {
	return array( '0' => '정규시즌', '1' => '시범경기', '4' => '와일드카드', '3' => '준플레이오프',
		'5' => '플레이오프', '7' => '한국시리즈', '8' => '국제대회', '9' => '올스타전' );
}

/* ---------- 설정 ---------- */
function kbo26_settings() {
	$defaults = array(
		'season'     => '2026',
		'home_page'  => '/kbo-schedule/',   // 남은 일정(랜딩) 페이지 주소
		'day_page'   => '/kbo-day/',        // [kbo_day] 를 넣은 날짜별 안내 페이지
		'tv_page'    => '/kbo-tv-channel/', // TV 중계 채널 안내 페이지
		'tving_page' => '/kbo-tving/',      // 모바일(티빙) 시청법 페이지
	);
	return wp_parse_args( (array) get_option( 'kbo26_settings', array() ), $defaults );
}

function kbo26_link( $value ) {
	return preg_match( '#^https?://#', $value ) ? $value : home_url( '/' . ltrim( $value, '/' ) );
}

/* ---------- 일정 받기 ---------- */
function kbo26_strip( $s ) {
	$s = html_entity_decode( preg_replace( '/<[^>]+>/', ' ', (string) $s ), ENT_QUOTES, 'UTF-8' );
	return trim( preg_replace( '/\s+/u', ' ', $s ) );
}

function kbo26_parse( $data, $season, $series ) {
	$games = array();
	$day   = null;
	foreach ( (array) ( $data['rows'] ?? array() ) as $row ) {
		$cells = $row['row'] ?? array();
		if ( $cells && ( $cells[0]['Class'] ?? '' ) === 'day' ) {
			$day   = kbo26_strip( $cells[0]['Text'] );
			$cells = array_slice( $cells, 1 );
		}
		if ( count( $cells ) < 8 || ! $day || ! preg_match( '/(\d+)\.(\d+)/', $day, $md ) ) {
			continue;
		}
		$play = (string) ( $cells[1]['Text'] ?? '' );
		preg_match_all( '#<span[^>]*>(.*?)</span>#u', $play, $sp );
		$teams = array_values( array_filter( $sp[1], function ( $x ) { return $x !== 'vs' && ! ctype_digit( $x ); } ) );
		preg_match_all( '#<span class="(?:win|lose|same)">(\d+)</span>#', $play, $sc );
		preg_match( '/gameId=(\w+)/', (string) ( $cells[2]['Text'] ?? '' ), $gid );
		$note    = kbo26_strip( $cells[7]['Text'] ?? '' );
		$tv      = kbo26_strip( $cells[4]['Text'] ?? '' );
		$games[] = array(
			'd'  => sprintf( '%s-%02d-%02d', $season, $md[1], $md[2] ),
			't'  => kbo26_strip( $cells[0]['Text'] ?? '' ),
			'a'  => $teams ? $teams[0] : '',
			'h'  => $teams ? end( $teams ) : '',
			'sc' => count( $sc[1] ) === 2 ? array_map( 'intval', $sc[1] ) : null,
			'tv' => $tv === '' ? array() : explode( ' ', $tv ),
			'st' => kbo26_strip( $cells[6]['Text'] ?? '' ),
			'n'  => $note === '-' ? '' : $note,
			'sr' => $series,
			'id' => $gid[1] ?? '',
		);
	}
	return $games;
}

function kbo26_fetch_month( $season, $month, $sr ) {
	$res = wp_remote_post( KBO26_URL, array(
		'timeout' => 20,
		'headers' => array(
			'Content-Type'     => 'application/x-www-form-urlencoded; charset=UTF-8',
			'Referer'          => 'https://www.koreabaseball.com/Schedule/Schedule.aspx',
			'X-Requested-With' => 'XMLHttpRequest',
			'User-Agent'       => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
		),
		'body'    => array( 'leId' => '1', 'srIdList' => $sr, 'seasonId' => $season,
			'gameMonth' => sprintf( '%02d', $month ), 'teamId' => '' ),
	) );
	if ( is_wp_error( $res ) || 200 !== wp_remote_retrieve_response_code( $res ) ) {
		return null;
	}
	$json = json_decode( wp_remote_retrieve_body( $res ), true );
	return is_array( $json ) ? $json : null;
}

/**
 * 일정을 다시 받는다. $months 가 null 이면 시즌 전체, 아니면 그 달만 받아 기존 일정과 합친다.
 * 한 번이라도 실패하면 기존 일정을 그대로 둔다 (빈 일정으로 덮어쓰지 않음).
 */
function kbo26_refresh( $months = null ) {
	$cfg    = kbo26_settings();
	$season = preg_replace( '/\D/', '', $cfg['season'] );
	$all    = null === $months;
	$months = $all ? range( 2, 12 ) : array_unique( array_map( 'intval', $months ) );
	@set_time_limit( 180 );
	$fresh = array();
	foreach ( kbo26_series() as $sr => $name ) {
		foreach ( $months as $m ) {
			$data = kbo26_fetch_month( $season, $m, (string) $sr );
			if ( null === $data ) {
				update_option( 'kbo26_last_error', current_time( 'mysql' ) . ' KBO 일정 서버에 연결하지 못했습니다.', false );
				return false;
			}
			$fresh = array_merge( $fresh, kbo26_parse( $data, $season, $name ) );
		}
	}
	$old   = kbo26_get_schedule();
	$games = array();
	if ( ! $all && ( $old['season'] ?? '' ) === $season ) {
		foreach ( $old['games'] as $g ) { // 이번에 받은 달이 아닌 경기는 그대로 둔다
			if ( ! in_array( (int) substr( $g['d'], 5, 2 ), $months, true ) ) {
				$games[] = $g;
			}
		}
	}
	$games = array_merge( $games, $fresh );
	usort( $games, function ( $x, $y ) { return strcmp( $x['d'] . $x['t'], $y['d'] . $y['t'] ); } );
	update_option( 'kbo26_schedule', array(
		'season'  => $season,
		'updated' => wp_date( 'Y-m-d\TH:i:sP', null, new DateTimeZone( 'Asia/Seoul' ) ),
		'source'  => 'KBO 공식 일정',
		'games'   => $games,
	), false );
	delete_option( 'kbo26_last_error' );
	return count( $games );
}

function kbo26_get_schedule() {
	$data = get_option( 'kbo26_schedule' );
	if ( ! is_array( $data ) || empty( $data['games'] ) ) { // 처음에는 함께 들어 있는 일정으로 시작
		$file = plugin_dir_path( KBO26_FILE ) . 'data/schedule.json';
		$data = file_exists( $file ) ? json_decode( file_get_contents( $file ), true ) : array( 'games' => array() );
	}
	return $data;
}

/* 30분마다 이번 달·다음 달만 다시 받는다 */
add_filter( 'cron_schedules', function ( $s ) {
	$s['kbo26_30min'] = array( 'interval' => 1800, 'display' => '30분마다' );
	return $s;
} );
add_action( 'kbo26_cron', function () {
	$now = new DateTime( 'now', new DateTimeZone( 'Asia/Seoul' ) );
	$m   = (int) $now->format( 'n' );
	kbo26_refresh( array( $m, $m === 12 ? 12 : $m + 1 ) );
} );
register_activation_hook( __FILE__, function () {
	if ( ! wp_next_scheduled( 'kbo26_cron' ) ) {
		wp_schedule_event( time() + 60, 'kbo26_30min', 'kbo26_cron' );
	}
} );
register_deactivation_hook( __FILE__, function () {
	wp_clear_scheduled_hook( 'kbo26_cron' );
} );

/* ---------- 일정 데이터 주소 (REST) ---------- */
add_action( 'rest_api_init', function () {
	register_rest_route( 'kbo2026/v1', '/schedule', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => function () {
			$r = rest_ensure_response( kbo26_get_schedule() );
			$r->header( 'Cache-Control', 'public, max-age=300' );
			return $r;
		},
	) );
} );

/* ---------- 화면 ---------- */
add_action( 'wp_enqueue_scripts', function () {
	$base = plugin_dir_url( KBO26_FILE ) . 'assets/';
	// 글 스타일(배경색 소제목, 빨간 버튼 등)은 안내 글에도 쓰이므로 모든 페이지에 넣는다 (약 6KB)
	wp_enqueue_style( 'kbo26', $base . 'kbo.css', array(), KBO26_VER );
	wp_register_script( 'kbo26', $base . 'kbo.js', array(), KBO26_VER, true );
	$cfg = kbo26_settings();
	wp_localize_script( 'kbo26', 'KBO26', array(
		'api'   => esc_url_raw( rest_url( 'kbo2026/v1/schedule' ) ),
		'home'  => kbo26_link( $cfg['home_page'] ),
		'day'   => kbo26_link( $cfg['day_page'] ),
		'tv'    => kbo26_link( $cfg['tv_page'] ),
		'tving' => kbo26_link( $cfg['tving_page'] ),
	) );
} );

function kbo26_block( $type, $atts = array() ) {
	wp_enqueue_script( 'kbo26' );
	$attr = '';
	foreach ( $atts as $k => $v ) {
		$attr .= sprintf( ' data-%s="%s"', esc_attr( $k ), esc_attr( $v ) );
	}
	return sprintf( '<div class="kbo26" data-kbo="%s"%s><p class="kbo26-loading">일정을 불러오는 중입니다…</p></div>', esc_attr( $type ), $attr );
}
add_shortcode( 'kbo_next', function () { return kbo26_block( 'next' ); } );
add_shortcode( 'kbo_schedule', function ( $a ) {
	$a = shortcode_atts( array( 'days' => '30', 'demo' => '0' ), $a );
	return kbo26_block( 'schedule', array( 'days' => (int) $a['days'], 'demo' => $a['demo'] ) );
} );
add_shortcode( 'kbo_day', function () { return kbo26_block( 'day' ); } );
add_shortcode( 'kbo_channels', function () { return kbo26_block( 'channels' ); } );
add_shortcode( 'kbo_channel_codes', function () { return kbo26_block( 'codes' ); } );

/* ---------- 관리자: 설정 > 프로야구 일정 ---------- */
add_action( 'admin_menu', function () {
	add_options_page( '프로야구 일정', '프로야구 일정', 'manage_options', 'kbo26', 'kbo26_admin_page' );
} );

add_action( 'admin_post_kbo26_save', function () {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( '권한이 없습니다.' );
	}
	check_admin_referer( 'kbo26_save' );
	$in  = wp_unslash( $_POST );
	$cfg = array();
	foreach ( array( 'season', 'home_page', 'day_page', 'tv_page', 'tving_page' ) as $k ) {
		$cfg[ $k ] = sanitize_text_field( $in[ $k ] ?? '' );
	}
	update_option( 'kbo26_settings', $cfg );
	$msg = 'saved';
	if ( ! empty( $in['refresh'] ) ) {
		$msg = false === kbo26_refresh() ? 'fail' : 'refreshed';
	}
	wp_safe_redirect( admin_url( 'options-general.php?page=kbo26&msg=' . $msg ) );
	exit;
} );

function kbo26_admin_page() {
	$cfg  = kbo26_settings();
	$data = kbo26_get_schedule();
	$msg  = sanitize_key( $_GET['msg'] ?? '' );
	$msgs = array( 'saved' => '저장했습니다.', 'refreshed' => '일정을 새로 받았습니다.', 'fail' => 'KBO 일정 서버에 연결하지 못했습니다. 기존 일정을 그대로 둡니다.' );
	$next = wp_next_scheduled( 'kbo26_cron' );
	?>
	<div class="wrap">
		<h1>2026 프로야구 일정 중계</h1>
		<?php if ( isset( $msgs[ $msg ] ) ) : ?>
			<div class="notice notice-<?php echo 'fail' === $msg ? 'error' : 'success'; ?>"><p><?php echo esc_html( $msgs[ $msg ] ); ?></p></div>
		<?php endif; ?>
		<p>저장된 경기 <b><?php echo count( $data['games'] ?? array() ); ?></b>개 · 마지막 갱신 <b><?php echo esc_html( $data['updated'] ?? '-' ); ?></b>
			· 다음 자동 갱신 <b><?php echo $next ? esc_html( wp_date( 'Y-m-d H:i', $next ) ) : '예약 없음 (플러그인을 껐다 켜 주세요)'; ?></b></p>
		<?php if ( get_option( 'kbo26_last_error' ) ) : ?>
			<p style="color:#b32d2e">최근 오류: <?php echo esc_html( get_option( 'kbo26_last_error' ) ); ?></p>
		<?php endif; ?>
		<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
			<input type="hidden" name="action" value="kbo26_save">
			<?php wp_nonce_field( 'kbo26_save' ); ?>
			<table class="form-table" role="presentation">
				<tr><th><label for="season">시즌</label></th><td><input id="season" name="season" value="<?php echo esc_attr( $cfg['season'] ); ?>" class="small-text"></td></tr>
				<tr><th><label for="home_page">남은 일정 페이지</label></th><td><input id="home_page" name="home_page" value="<?php echo esc_attr( $cfg['home_page'] ); ?>" class="regular-text"><p class="description">[kbo_schedule] 을 넣은 페이지 주소. 첫 화면이면 <code>/</code></p></td></tr>
				<tr><th><label for="day_page">날짜별 안내 페이지</label></th><td><input id="day_page" name="day_page" value="<?php echo esc_attr( $cfg['day_page'] ); ?>" class="regular-text"><p class="description">[kbo_day] 를 넣은 페이지 주소</p></td></tr>
				<tr><th><label for="tv_page">TV 중계 채널 페이지</label></th><td><input id="tv_page" name="tv_page" value="<?php echo esc_attr( $cfg['tv_page'] ); ?>" class="regular-text"></td></tr>
				<tr><th><label for="tving_page">모바일 시청법 페이지</label></th><td><input id="tving_page" name="tving_page" value="<?php echo esc_attr( $cfg['tving_page'] ); ?>" class="regular-text"></td></tr>
			</table>
			<p>
				<?php submit_button( '저장', 'primary', 'save', false ); ?>
				<?php submit_button( '저장하고 지금 일정 새로 받기 (1~2분)', 'secondary', 'refresh', false ); ?>
			</p>
		</form>
	</div>
	<?php
}
